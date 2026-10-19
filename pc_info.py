#!/usr/bin/env python3
"""
pc_info.py - Collects as much info about your PC as it can and dumps it
into a text file (pc_info_<hostname>_<timestamp>.txt).

Works on Windows, Linux and macOS using only the standard library.
If you have psutil installed (pip install psutil) you get extra detail
(per-core CPU, temperatures, fans, battery, open connections, etc.).

Usage:
    python pc_info.py
    python pc_info.py -o my_report.txt
    python pc_info.py --software      (also list installed software; slower)
"""

import argparse
import datetime
import getpass
import os
import platform
import shutil
import socket
import subprocess
import sys

try:
    import psutil
except ImportError:
    psutil = None

OS = platform.system()  # 'Windows', 'Linux', 'Darwin'


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def run(cmd, timeout=30, shell=False):
    """Run a command and return its stdout as text ('' on failure)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
            errors="replace",
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def powershell(script, timeout=45):
    """Run a PowerShell snippet (Windows only)."""
    return run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


def human_bytes(n):
    if n is None:
        return "N/A"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0:
            return f"{n:,.2f} {unit}"
        n /= 1024.0
    return f"{n:,.2f} EB"


def human_time(seconds):
    seconds = int(seconds)
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return f"{d}d {h}h {m}m {s}s"


def read_file(path):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""


class Report:
    def __init__(self):
        self.lines = []

    def section(self, title):
        self.lines.append("")
        self.lines.append("=" * 70)
        self.lines.append(f"  {title}")
        self.lines.append("=" * 70)

    def add(self, label, value=""):
        if value == "" or value is None:
            self.lines.append(f"{label}")
        else:
            self.lines.append(f"{label:<28}: {value}")

    def text(self, block):
        if block:
            self.lines.append(block)

    def __str__(self):
        return "\n".join(self.lines) + "\n"


# --------------------------------------------------------------------------
# Collectors
# --------------------------------------------------------------------------
def collect_system(r):
    r.section("SYSTEM / OPERATING SYSTEM")
    r.add("Hostname", socket.gethostname())
    r.add("FQDN", socket.getfqdn())
    r.add("Current user", getpass.getuser())
    r.add("OS", OS)
    r.add("OS release", platform.release())
    r.add("OS version", platform.version())
    r.add("Platform string", platform.platform())
    r.add("Architecture", " ".join(platform.architecture()))
    r.add("Machine", platform.machine())
    r.add("Processor (platform)", platform.processor())
    r.add("Report generated", datetime.datetime.now().isoformat(timespec="seconds"))

    if psutil:
        boot = datetime.datetime.fromtimestamp(psutil.boot_time())
        r.add("Boot time", boot.strftime("%Y-%m-%d %H:%M:%S"))
        r.add("Uptime", human_time((datetime.datetime.now() - boot).total_seconds()))

    if OS == "Windows":
        r.text(powershell(
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object Caption,Version,BuildNumber,OSArchitecture,InstallDate,"
            "RegisteredUser,SerialNumber | Format-List | Out-String"
        ))
    elif OS == "Linux":
        osr = read_file("/etc/os-release")
        if osr:
            r.add("/etc/os-release")
            r.text(osr)
        r.add("Kernel", run(["uname", "-a"]))
        r.add("Desktop session", os.environ.get("XDG_CURRENT_DESKTOP", "N/A"))
    elif OS == "Darwin":
        r.text(run(["sw_vers"]))


def collect_hardware_identity(r):
    r.section("MOTHERBOARD / BIOS / MACHINE")
    if OS == "Windows":
        r.text(powershell(
            "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,"
            "SystemType,TotalPhysicalMemory,NumberOfProcessors | Format-List | Out-String"
        ))
        r.text(powershell(
            "Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product,"
            "SerialNumber,Version | Format-List | Out-String"
        ))
        r.text(powershell(
            "Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,"
            "ReleaseDate,SerialNumber | Format-List | Out-String"
        ))
    elif OS == "Linux":
        base = "/sys/devices/virtual/dmi/id/"
        for label, fname in [
            ("System vendor", "sys_vendor"),
            ("Product name", "product_name"),
            ("Product version", "product_version"),
            ("Board vendor", "board_vendor"),
            ("Board name", "board_name"),
            ("BIOS vendor", "bios_vendor"),
            ("BIOS version", "bios_version"),
            ("BIOS date", "bios_date"),
            ("Chassis type", "chassis_type"),
        ]:
            val = read_file(base + fname)
            if val:
                r.add(label, val)
        model = read_file("/proc/device-tree/model")  # Raspberry Pi etc.
        if model:
            r.add("Device-tree model", model.strip("\x00"))
    elif OS == "Darwin":
        r.text(run(["system_profiler", "SPHardwareDataType"], timeout=60))


def collect_cpu(r):
    r.section("CPU")
    r.add("Architecture", platform.machine())
    if OS == "Windows":
        r.text(powershell(
            "Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,"
            "NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,L2CacheSize,"
            "L3CacheSize,SocketDesignation | Format-List | Out-String"
        ))
    elif OS == "Linux":
        out = run(["lscpu"])
        if out:
            r.text(out)
        else:
            info = read_file("/proc/cpuinfo")
            for line in info.splitlines():
                if line.startswith(("model name", "cpu MHz", "cache size", "flags")):
                    r.text(line)
                    if line.startswith("flags"):
                        break
    elif OS == "Darwin":
        r.add("Brand", run(["sysctl", "-n", "machdep.cpu.brand_string"]))
        r.add("Cores (physical)", run(["sysctl", "-n", "hw.physicalcpu"]))
        r.add("Cores (logical)", run(["sysctl", "-n", "hw.logicalcpu"]))
        r.add("CPU frequency (Hz)", run(["sysctl", "-n", "hw.cpufrequency"]))

    r.add("Logical CPUs (os)", os.cpu_count())
    if psutil:
        r.add("Physical cores", psutil.cpu_count(logical=False))
        r.add("Logical cores", psutil.cpu_count(logical=True))
        freq = psutil.cpu_freq()
        if freq:
            r.add("Frequency current", f"{freq.current:.0f} MHz")
            r.add("Frequency min/max", f"{freq.min:.0f} / {freq.max:.0f} MHz")
        r.add("Total usage now", f"{psutil.cpu_percent(interval=1)} %")
        per_core = psutil.cpu_percent(interval=0.5, percpu=True)
        r.add("Per-core usage", ", ".join(f"{p:.0f}%" for p in per_core))
        try:
            la = psutil.getloadavg()
            r.add("Load average (1/5/15)", ", ".join(f"{x:.2f}" for x in la))
        except Exception:
            pass


def collect_memory(r):
    r.section("MEMORY (RAM)")
    if psutil:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        r.add("Total RAM", human_bytes(vm.total))
        r.add("Available RAM", human_bytes(vm.available))
        r.add("Used RAM", f"{human_bytes(vm.used)} ({vm.percent}%)")
        r.add("Swap/pagefile total", human_bytes(sw.total))
        r.add("Swap/pagefile used", f"{human_bytes(sw.used)} ({sw.percent}%)")
    elif OS == "Linux":
        for line in read_file("/proc/meminfo").splitlines()[:6]:
            r.text(line)

    if OS == "Windows":
        r.add("RAM modules")
        r.text(powershell(
            "Get-CimInstance Win32_PhysicalMemory | Select-Object BankLabel,Manufacturer,"
            "PartNumber,Capacity,Speed,ConfiguredClockSpeed,SMBIOSMemoryType | "
            "Format-Table -AutoSize | Out-String -Width 200"
        ))
    elif OS == "Linux":
        out = run(["dmidecode", "-t", "memory"])  # needs root
        if out:
            r.add("RAM modules (dmidecode)")
            r.text(out)
        else:
            r.add("RAM modules", "run as root/sudo to see module details (dmidecode)")
    elif OS == "Darwin":
        r.text(run(["system_profiler", "SPMemoryDataType"], timeout=60))


def collect_gpu(r):
    r.section("GPU / GRAPHICS")
    if OS == "Windows":
        r.text(powershell(
            "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,"
            "DriverVersion,DriverDate,VideoProcessor,CurrentHorizontalResolution,"
            "CurrentVerticalResolution,CurrentRefreshRate | Format-List | Out-String"
        ))
    elif OS == "Linux":
        out = run("lspci | grep -iE 'vga|3d|display'", shell=True)
        r.text(out or "No lspci output (install pciutils)")
    elif OS == "Darwin":
        r.text(run(["system_profiler", "SPDisplaysDataType"], timeout=60))

    if shutil.which("nvidia-smi"):
        r.add("")
        r.add("NVIDIA (nvidia-smi)")
        r.text(run([
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used,temperature.gpu,"
            "utilization.gpu,power.draw",
            "--format=csv",
        ]))


def collect_disks(r):
    r.section("STORAGE / DISKS")
    if OS == "Windows":
        r.add("Physical disks")
        r.text(powershell(
            "Get-CimInstance Win32_DiskDrive | Select-Object Model,InterfaceType,"
            "MediaType,Size,SerialNumber,Partitions | Format-Table -AutoSize | "
            "Out-String -Width 200"
        ))
    elif OS == "Linux":
        r.add("Block devices (lsblk)")
        r.text(run(["lsblk", "-o", "NAME,MODEL,SIZE,TYPE,FSTYPE,MOUNTPOINT,ROTA"]))
    elif OS == "Darwin":
        r.text(run(["diskutil", "list"]))

    r.add("")
    r.add("Mounted volumes / usage")
    if psutil:
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                r.add(
                    f"{part.device} -> {part.mountpoint}",
                    f"{part.fstype} | total {human_bytes(u.total)} | used "
                    f"{human_bytes(u.used)} ({u.percent}%) | free {human_bytes(u.free)}",
                )
            except Exception:
                r.add(f"{part.device} -> {part.mountpoint}", f"{part.fstype} (no access)")
        io = psutil.disk_io_counters()
        if io:
            r.add("Total read since boot", human_bytes(io.read_bytes))
            r.add("Total written since boot", human_bytes(io.write_bytes))
    else:
        root = os.path.abspath(os.sep)
        total, used, free = shutil.disk_usage(root)
        r.add(root, f"total {human_bytes(total)} | used {human_bytes(used)} | free {human_bytes(free)}")


def collect_network(r):
    r.section("NETWORK")
    r.add("Hostname", socket.gethostname())
    try:
        r.add("Primary local IP", socket.gethostbyname(socket.gethostname()))
    except Exception:
        pass

    if psutil:
        r.add("")
        r.add("Interfaces")
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            state = "UP" if st and st.isup else "DOWN"
            speed = f"{st.speed} Mbps" if st and st.speed else "unknown speed"
            r.add(f"  [{name}]", f"{state}, {speed}")
            for a in addrs:
                fam = getattr(a.family, "name", str(a.family))
                fam = {"AF_INET": "IPv4", "AF_INET6": "IPv6",
                       "AF_LINK": "MAC", "AF_PACKET": "MAC"}.get(fam, fam)
                r.add(f"      {fam}", a.address)
        io = psutil.net_io_counters()
        r.add("Total sent since boot", human_bytes(io.bytes_sent))
        r.add("Total received since boot", human_bytes(io.bytes_recv))
    else:
        if OS == "Windows":
            r.text(run(["ipconfig", "/all"]))
        elif OS == "Linux":
            r.text(run(["ip", "-br", "addr"]) or run(["ifconfig"]))
        elif OS == "Darwin":
            r.text(run(["ifconfig"]))

    if OS == "Windows":
        r.add("")
        r.add("Wi-Fi (current connection, no passwords)")
        r.text(run(["netsh", "wlan", "show", "interfaces"]))
    elif OS == "Linux" and shutil.which("nmcli"):
        r.add("")
        r.add("Network devices (nmcli)")
        r.text(run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]))

    r.add("")
    r.add("DNS servers")
    if OS == "Linux":
        for line in read_file("/etc/resolv.conf").splitlines():
            if line.startswith("nameserver"):
                r.text("  " + line)
    elif OS == "Windows":
        r.text(powershell(
            "Get-DnsClientServerAddress -AddressFamily IPv4 | "
            "Select-Object InterfaceAlias,ServerAddresses | Format-Table -AutoSize | Out-String"
        ))
    elif OS == "Darwin":
        r.text(run(["scutil", "--dns"])[:1500])


def collect_battery_sensors(r):
    r.section("BATTERY / SENSORS")
    if psutil:
        try:
            b = psutil.sensors_battery()
            if b:
                r.add("Battery", f"{b.percent:.0f}% | plugged in: {b.power_plugged}")
                if b.secsleft and b.secsleft > 0:
                    r.add("Time left", human_time(b.secsleft))
            else:
                r.add("Battery", "none detected (desktop?)")
        except Exception:
            r.add("Battery", "unavailable")
        try:
            temps = psutil.sensors_temperatures()
            for chip, entries in temps.items():
                for e in entries:
                    r.add(f"Temp {chip}/{e.label or 'sensor'}", f"{e.current} C")
        except Exception:
            r.add("Temperatures", "not available on this OS")
        try:
            fans = psutil.sensors_fans()
            for chip, entries in fans.items():
                for e in entries:
                    r.add(f"Fan {chip}/{e.label or 'fan'}", f"{e.current} RPM")
        except Exception:
            pass
    else:
        r.add("Info", "install psutil for battery/temperature/fan data")
    if OS == "Windows":
        r.text(powershell(
            "Get-CimInstance Win32_Battery | Select-Object Name,EstimatedChargeRemaining,"
            "BatteryStatus,DesignVoltage | Format-List | Out-String"
        ))


def collect_displays_peripherals(r):
    r.section("DISPLAYS / USB / PERIPHERALS")
    if OS == "Windows":
        r.add("Monitors")
        r.text(powershell(
            "Get-CimInstance Win32_DesktopMonitor | Select-Object Name,ScreenWidth,"
            "ScreenHeight | Format-Table -AutoSize | Out-String"
        ))
        r.add("Sound devices")
        r.text(powershell(
            "Get-CimInstance Win32_SoundDevice | Select-Object Name,Manufacturer | "
            "Format-Table -AutoSize | Out-String -Width 200"
        ))
        r.add("USB devices")
        r.text(powershell(
            "Get-PnpDevice -PresentOnly -Class USB | Select-Object FriendlyName,Status | "
            "Format-Table -AutoSize | Out-String -Width 200"
        ))
    elif OS == "Linux":
        r.add("USB devices (lsusb)")
        r.text(run(["lsusb"]) or "lsusb not available")
        r.add("")
        r.add("PCI devices (lspci)")
        r.text(run(["lspci"]) or "lspci not available")
        if shutil.which("xrandr"):
            r.add("")
            r.add("Displays (xrandr)")
            r.text(run(["xrandr", "--query"]))
    elif OS == "Darwin":
        r.text(run(["system_profiler", "SPUSBDataType"], timeout=60))
        r.text(run(["system_profiler", "SPAudioDataType"], timeout=60))


def collect_processes(r):
    r.section("RUNNING PROCESSES (top 25 by memory)")
    if psutil:
        procs = []
        for p in psutil.process_iter(["pid", "name", "username", "memory_info"]):
            try:
                mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
                procs.append((mem, p.info["pid"], p.info["name"], p.info["username"]))
            except Exception:
                continue
        procs.sort(reverse=True)
        r.add("Total processes", len(procs))
        for mem, pid, name, user in procs[:25]:
            r.text(f"  {human_bytes(mem):>12}  PID {pid:<7} {name}  ({user})")
    else:
        if OS == "Windows":
            r.text(run(["tasklist"]))
        else:
            r.text(run("ps aux --sort=-%mem | head -26", shell=True))


def collect_python(r):
    r.section("PYTHON ENVIRONMENT")
    r.add("Python version", sys.version.replace("\n", " "))
    r.add("Executable", sys.executable)
    r.add("Implementation", platform.python_implementation())
    r.add("Compiler", platform.python_compiler())
    r.add("psutil installed", "yes" if psutil else "no (pip install psutil for more detail)")


def collect_software(r):
    r.section("INSTALLED SOFTWARE")
    if OS == "Windows":
        r.text(powershell(
            "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,"
            "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
            "| Where-Object DisplayName | Select-Object DisplayName,DisplayVersion,Publisher "
            "| Sort-Object DisplayName | Format-Table -AutoSize | Out-String -Width 250",
            timeout=90,
        ))
    elif OS == "Linux":
        if shutil.which("dpkg"):
            r.text(run("dpkg-query -W -f='${Package} ${Version}\\n'", shell=True, timeout=60))
        elif shutil.which("rpm"):
            r.text(run("rpm -qa | sort", shell=True, timeout=60))
        elif shutil.which("pacman"):
            r.text(run(["pacman", "-Q"]))
    elif OS == "Darwin":
        r.text(run(["system_profiler", "SPApplicationsDataType"], timeout=180))


def collect_paths(r):
    r.section("ENVIRONMENT (safe subset)")
    # Only non-sensitive variables; full env can contain tokens/passwords.
    for key in ("PATH", "HOME", "USERPROFILE", "SHELL", "LANG", "TEMP", "TMP",
                "COMPUTERNAME", "PROCESSOR_IDENTIFIER", "NUMBER_OF_PROCESSORS"):
        val = os.environ.get(key)
        if val:
            r.add(key, val)
    r.add("Timezone", datetime.datetime.now().astimezone().tzname())
    r.add("UTC offset", str(datetime.datetime.now().astimezone().utcoffset()))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Dump PC information into a text file.")
    parser.add_argument("-o", "--output", help="output file name")
    parser.add_argument("--software", action="store_true",
                        help="also list installed software (slower)")
    args = parser.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = args.output or f"pc_info_{socket.gethostname()}_{stamp}.txt"

    r = Report()
    r.lines.append("#" * 70)
    r.lines.append("#  PC INFORMATION REPORT")
    r.lines.append("#" * 70)

    steps = [
        ("system", collect_system),
        ("motherboard/BIOS", collect_hardware_identity),
        ("CPU", collect_cpu),
        ("memory", collect_memory),
        ("GPU", collect_gpu),
        ("disks", collect_disks),
        ("network", collect_network),
        ("battery/sensors", collect_battery_sensors),
        ("peripherals", collect_displays_peripherals),
        ("processes", collect_processes),
        ("python", collect_python),
        ("environment", collect_paths),
    ]
    if args.software:
        steps.append(("software", collect_software))

    for name, func in steps:
        print(f"Collecting {name} ...")
        try:
            func(r)
        except Exception as exc:  # never let one section kill the whole report
            r.section(f"{name.upper()} (error)")
            r.add("Error", repr(exc))

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(str(r))

    print(f"\nDone! Saved to: {os.path.abspath(out_file)}")
    if not psutil:
        print("Tip: run 'pip install psutil' and re-run for more detail.")


if __name__ == "__main__":
    main()
