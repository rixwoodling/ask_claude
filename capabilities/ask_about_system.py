import os
import platform
import time
import psutil

CAPABILITY = "system"

DESCRIPTION = (
    "Provides information about the local computer, including operating "
    "system, architecture, CPU count, hostname, and uptime."
)



REQUEST_SCHEMA = {
    "request": "optional; no fields are currently required",
}

PLANNER_INSTRUCTIONS = (
    "Use the system capability for questions about the local computer, "
    "including operating system, architecture, CPU count, hostname, "
    "or uptime. The request can be an empty object."
)

def run_lookup(request):
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    cpu_frequency = psutil.cpu_freq()
    load_average = getattr(psutil, "getloadavg", lambda: None)()

    network = {}
    try:
        addresses = psutil.net_if_addrs()
        counters = psutil.net_io_counters(pernic=True)

        for interface, entries in addresses.items():
            interface_addresses = []
            for entry in entries:
                address = {
                    "family": str(entry.family),
                    "address": entry.address,
                }
                if entry.netmask:
                    address["netmask"] = entry.netmask
                if entry.broadcast:
                    address["broadcast"] = entry.broadcast
                interface_addresses.append(address)

            interface_data = {
                "addresses": interface_addresses,
            }

            counter = counters.get(interface)
            if counter:
                interface_data["bytes_sent"] = counter.bytes_sent
                interface_data["bytes_received"] = counter.bytes_recv

            network[interface] = interface_data
    except (OSError, AttributeError):
        network = {}

    result = {
        "hostname": platform.node(),
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "physical_cpu_cores": psutil.cpu_count(logical=False),
        "logical_cpu_cores": psutil.cpu_count(logical=True),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "boot_time": time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(psutil.boot_time()),
        ),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "memory": {
            "total_bytes": memory.total,
            "available_bytes": memory.available,
            "used_bytes": memory.used,
            "free_bytes": memory.free,
            "percent_used": memory.percent,
        },
        "swap": {
            "total_bytes": swap.total,
            "used_bytes": swap.used,
            "free_bytes": swap.free,
            "percent_used": swap.percent,
        },
        "disk": {
            "path": "/",
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "percent_used": disk.percent,
        },
        "network": network,
        "process": {
            "pid": os.getpid(),
            "python_version": platform.python_version(),
        },
    }

    if cpu_frequency:
        result["cpu_frequency_mhz"] = {
            "current": cpu_frequency.current,
            "min": cpu_frequency.min,
            "max": cpu_frequency.max,
        }

    if load_average is not None:
        result["load_average"] = {
            "1_minute": load_average[0],
            "5_minutes": load_average[1],
            "15_minutes": load_average[2],
        }

    return result

