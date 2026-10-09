#!/usr/bin/env python3
"""ask_about_network.py - network/IP discovery capability."""

import ipaddress
import json
import platform
import re
import socket
import subprocess
import urllib.request

CAPABILITY = "network"
DESCRIPTION = (
    "Inspect the current computer's network: internal/local IPv4 addresses, "
    "public/external IPv4 address, default gateway, interfaces, subnet information, "
    "and nearby devices learned from the local ARP/neighbor table. "
    "Can optionally perform a lightweight ping sweep of directly connected private networks."
)


def _run(args, timeout=5):
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, check=False)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _interfaces():
    system = platform.system()
    items = []

    if system == "Darwin":
        out = _run(["ifconfig"])
        current = None
        for line in out.splitlines():
            if line and not line.startswith((" ", "\t")):
                current = line.split(":", 1)[0]
            m = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", line)
            if current and m and not m.group(1).startswith("127."):
                items.append({"interface": current, "ipv4": m.group(1)})
    elif system == "Linux":
        out = _run(["ip", "-o", "-4", "addr", "show"])
        for line in out.splitlines():
            m = re.search(
                r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line
            )
            if m and not m.group(2).startswith("127."):
                items.append({
                    "interface": m.group(1),
                    "ipv4": m.group(2),
                    "prefix": int(m.group(3)),
                })
    else:
        try:
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                if not ip.startswith("127."):
                    items.append({"interface": socket.gethostname(), "ipv4": ip})
        except socket.error:
            pass

    seen, result = set(), []
    for item in items:
        key = (item["interface"], item["ipv4"])
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _gateway():
    system = platform.system()
    if system == "Darwin":
        m = re.search(r"gateway:\s+(\S+)",
                      _run(["route", "-n", "get", "default"]))
    elif system == "Linux":
        m = re.search(r"default via (\S+)",
                      _run(["ip", "route", "show", "default"]))
    else:
        m = None
    return m.group(1) if m else None


def _neighbors():
    system = platform.system()
    result = []

    if system == "Darwin":
        for line in _run(["arp", "-an"]).splitlines():
            m = re.search(
                r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:.-]+)\s+on\s+(\S+)",
                line,
            )
            if m:
                result.append({
                    "ip": m.group(1),
                    "mac": m.group(2),
                    "interface": m.group(3),
                })
    elif system == "Linux":
        for line in _run(["ip", "neigh", "show"]).splitlines():
            m = re.search(
                r"^(\d+\.\d+\.\d+\.\d+)\s+dev\s+(\S+)"
                r"(?:\s+lladdr\s+([0-9a-fA-F:]+))?(?:\s+(\S+))?",
                line,
            )
            if m:
                result.append({
                    "ip": m.group(1),
                    "interface": m.group(2),
                    "mac": m.group(3),
                    "state": m.group(4),
                })
    return result


def _public_ip():
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ask_about_network/1.0"}
            )
            with urllib.request.urlopen(req, timeout=4) as r:
                value = r.read().decode("utf-8", errors="replace").strip()
                if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", value):
                    return value
        except Exception:
            pass
    return None


def _listening_ports():
    """Return TCP/UDP ports listening on the local machine."""
    system = platform.system()
    result = []

    if system in {"Darwin", "Linux"}:
        # Prefer lsof because it is available on macOS and commonly on Linux.
        output = _run(
            ["lsof", "-nP", "-i", "-sTCP:LISTEN"],
            timeout=5,
        )
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 9:
                continue

            command = parts[0]
            pid = parts[1]
            name = parts[8]

            match = re.search(
                r"(?:TCP|UDP)\s+(?:[^:]+:)?(\d+)\s*(?:\([^)]*\))?$",
                name,
            )
            if not match:
                # Handle forms such as *:22 or 127.0.0.1:8080.
                match = re.search(r":(\d+)(?:\s+\(LISTEN\))?$", name)

            if match:
                port = int(match.group(1))
                protocol = "tcp" if "TCP" in name.upper() else "udp"
                result.append({
                    "protocol": protocol,
                    "port": port,
                    "process": command,
                    "pid": pid,
                    "endpoint": name,
                })

    elif system == "Windows":
        output = _run(["netstat", "-ano"], timeout=5)
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].upper() == "TCP":
                state = parts[3].upper()
                if state != "LISTENING":
                    continue
                endpoint = parts[1]
                pid = parts[4]
                match = re.search(r":(\d+)$", endpoint)
                if match:
                    result.append({
                        "protocol": "tcp",
                        "port": int(match.group(1)),
                        "pid": pid,
                        "endpoint": endpoint,
                        "state": state,
                    })

    # De-duplicate entries.
    seen = set()
    unique = []
    for item in result:
        key = (
            item.get("protocol"),
            item.get("port"),
            item.get("pid"),
            item.get("endpoint"),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return sorted(
        unique,
        key=lambda x: (x.get("port", 0), x.get("protocol", "")),
    )



def _ping(ip):
    if platform.system() == "Windows":
        args = ["ping", "-n", "1", "-w", "500", ip]
    else:
        args = ["ping", "-c", "1", "-W", "1", ip]
    try:
        return subprocess.run(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=2, check=False
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _scan(networks, limit=254):
    found = []
    for text in networks:
        try:
            net = ipaddress.ip_network(text, strict=False)
        except ValueError:
            continue
        if not net.is_private:
            continue
        hosts = list(net.hosts())
        if len(hosts) > limit:
            continue
        for host in hosts:
            ip = str(host)
            if _ping(ip):
                found.append(ip)
    return found


def _summary(data):
    parts = []
    internal = data.get("internal_ipv4") or []
    parts.append("Internal IP: " + (", ".join(internal) if internal else "unavailable"))
    parts.append("External IP: " + (data["external_ipv4"] or "unavailable"))
    if data.get("default_gateway"):
        parts.append("Gateway: " + data["default_gateway"])
    count = len(data.get("neighbors") or [])
    parts.append(f"{count} device(s) visible in the ARP/neighbor table")

    ports = data.get("listening_ports") or []
    if ports:
        port_numbers = sorted({
            int(item["port"])
            for item in ports
            if item.get("port") is not None
        })
        parts.append(
            "Listening ports: " + ", ".join(map(str, port_numbers))
        )
    else:
        parts.append("No listening ports were detected")

    return ". ".join(parts) + "."


def run_lookup(request):
    request = request or {}
    action = str(request.get("action", "summary")).lower().strip()
    if action not in {"summary", "map", "scan"}:
        action = "summary"

    interfaces = _interfaces()
    networks = []

    for item in interfaces:
        prefix = item.get("prefix")
        if prefix is not None:
            try:
                item["network"] = str(
                    ipaddress.ip_network(f'{item["ipv4"]}/{prefix}', strict=False)
                )
                networks.append(item["network"])
            except ValueError:
                pass

    result = {
        "internal_ipv4": [x["ipv4"] for x in interfaces],
        "external_ipv4": _public_ip(),
        "default_gateway": _gateway(),
        "interfaces": interfaces,
        "networks": sorted(set(networks)),
        "neighbors": _neighbors(),
        "listening_ports": _listening_ports(),
        "method": "OS interfaces, listening sockets, and ARP/neighbor information",
    }

    if action == "scan":
        result["ping_sweep"] = _scan(sorted(set(networks)))
        result["method"] += " plus a lightweight ICMP ping sweep"

    result["simple_summary"] = _summary(result)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "--action",
        choices=("summary", "map", "ports", "scan"),
        default="summary",
    )
    args = parser.parse_args()
    print(json.dumps(run_lookup({"action": args.action}), indent=2))
