import json
import os
import sys
import psutil

PROCESS_NAME = "ClassIsland.Desktop.exe"

def find_classisland_dir():
    """通过进程查找 ClassIsland 安装目录"""
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == PROCESS_NAME.lower():
                exe_path = proc.info['exe']
                if exe_path and os.path.isfile(exe_path):
                    return os.path.dirname(os.path.dirname(exe_path))  # 返回上一级目录
        except:
            continue
    return None

def find_profile_files(install_dir):
    """查找 data/Profiles/ 下的所有 .json 文件"""
    profiles_dir = os.path.join(install_dir, "data", "Profiles")
    if not os.path.isdir(profiles_dir):
        return []
    return [os.path.join(profiles_dir, f) for f in os.listdir(profiles_dir) if f.lower().endswith('.json')]

def find_default_json(install_dir):
    """在常见位置查找 Default.json"""
    candidates = [
        install_dir,
        os.path.join(install_dir, "Config"),
        os.path.join(install_dir, "Data"),
        os.path.join(install_dir, "Settings"),
    ]
    for folder in candidates:
        path = os.path.join(folder, "Default.json")
        if os.path.isfile(path):
            return path
    return None

def extract_break_periods(json_path):
    """提取所有 TimeType == 1 的时间段"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    periods_set = set()
    time_layouts = data.get("TimeLayouts", {})
    for layout in time_layouts.values():
        for item in layout.get("Layouts", []):
            if item.get("TimeType") == 1:
                start = item.get("StartTime")
                end = item.get("EndTime")
                if start and end:
                    periods_set.add((start[:5], end[:5]))
    sorted_periods = sorted(periods_set, key=lambda x: x[0])
    return [{"start": s, "end": e} for s, e in sorted_periods]

def import_periods(lock_config_path="lock_config.json"):
    """
    主函数：从 ClassIsland 导入时段并更新 lock_config.json
    返回 (success, message)
    """
    # 1. 查找 ClassIsland 安装目录
    install_dir = find_classisland_dir()
    if not install_dir:
        return False, "未找到运行的 ClassIsland 进程"

    # 2. 查找配置文件
    profiles = find_profile_files(install_dir)
    if profiles:
        config_path = profiles[0]  # 使用第一个配置文件
    else:
        config_path = find_default_json(install_dir)
        if not config_path:
            return False, f"未在 {install_dir} 下找到任何课表配置文件"

    # 3. 提取时段
    periods = extract_break_periods(config_path)

    # 4. 更新 lock_config.json
    if not os.path.exists(lock_config_path):
        return False, f"{lock_config_path} 不存在"

    with open(lock_config_path, 'r', encoding='utf-8') as f:
        lock_data = json.load(f)
    lock_data["periods"] = periods
    with open(lock_config_path, 'w', encoding='utf-8') as f:
        json.dump(lock_data, f, ensure_ascii=False, indent=4)

    return True, f"成功导入 {len(periods)} 个时段"