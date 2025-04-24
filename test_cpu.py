import cpuinfo

cpu_info = cpuinfo.get_cpu_info()
print(f"当前cpu信息:{cpu_info}")
print(f"当前cpu指令集支持：{cpu_info['flags']}")
