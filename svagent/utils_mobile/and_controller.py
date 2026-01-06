# pylint: disable=line-too-long, function-name-too-long
import base64
import getpass
import os
import subprocess
import time
from typing import Union

from ..link.utils import list_all_devices, execute_adb

from ..templates.packages import *
from .utils import print_with_color
from .utils import time_within_ten_secs


class AndroidController:
    def __init__(self, device, type="remote", instance=None):
        self.device = device
        self.type = type
        if instance is not None:
            if hasattr(instance, 'execute_remote_adb_command'):  # Remote instance
                self.remote_instance = instance
            else:
                raise ValueError("Invalid instance: must be a remote instance")
        else:
            raise ValueError("Instance is required for AndroidController")
        self.screenshot_dir = "/sdcard"
        self.xml_dir = "/sdcard"
        self.ac_xml_dir = "/sdcard/Android/data/com.example.android.xml_parser/files"
        self.width, self.height = self.get_device_size()
        self.viewport_size = (self.width, self.height)
        self.backslash = "\\"

    def execute_adb(self, adb_command, type="remote", output=True):
        if type == "remote":
            if hasattr(self, 'remote_instance') and self.remote_instance:
                result = self.remote_instance.execute_remote_adb_command(adb_command)
                if result and 'result' in result:
                    return result['result']
                elif result and 'error' in result:
                    return "ERROR"
                else:
                    return "ERROR"
            else:
                return "ERROR"
        else:
            raise ValueError(f"Unsupported type: {type}. Only 'remote' is supported.")

    def get_device_size(self):
        test_time = 0
        while test_time < 10:
            try:
                command = f"adb -s {self.device} shell wm size"
                output = self.execute_adb(command, self.type)
                resolution = output.split(":")[1].strip()
                width, height = resolution.split("x")
                return int(width), int(height)
            except Exception as e:
                test_time += 1
                time.sleep(5)
        assert False, "Error in getting device size"
        

    def get_screenshot(self, prefix, save_dir):
        cap_command = f"adb -s {self.device} shell screencap -p " \
                      f"{os.path.join(self.screenshot_dir, prefix + '.png').replace(self.backslash, '/')}"
        
        # 对于远程实例，使用增强的文件传输功能
        result = self.execute_adb(cap_command, self.type)
        if result != "ERROR":
            remote_path = f"{os.path.join(self.screenshot_dir, prefix + '.png').replace(self.backslash, '/')}"
            local_path = os.path.join(save_dir, prefix + '.png')
            
            # 使用增强的文件拉取功能
            # import ipdb; ipdb.set_trace()
            if hasattr(self.remote_instance, 'pull_file_from_device'):
                success = self.remote_instance.pull_file_from_device(remote_path, local_path)
                if success:
                    return local_path
                else:
                    return "ERROR"
            else:
                # 回退到原始方法
                pull_command = f"adb -s {self.device} pull {remote_path} {local_path}"
                result = self.execute_adb(pull_command, self.type)
                if result != "ERROR":
                    return local_path
        return result

    def save_screenshot(self, save_path):
        prefix = os.path.basename(save_path).replace('.png', '')
        remote_path = f"{os.path.join(self.screenshot_dir, prefix + '.png').replace(self.backslash, '/')}"
        cap_command = f"adb -s {self.device} shell screencap -p {remote_path}"
        # print("Capturing screenshot to:", remote_path, "capture command:", cap_command, "type:", self.type)
        result = self.execute_adb(cap_command, self.type)
        if result != "ERROR":
            # 对于远程实例，使用增强的文件传输功能
            if hasattr(self.remote_instance, 'pull_file_from_device'):
                success = self.remote_instance.pull_file_from_device(remote_path, save_path)
                if success:
                    return save_path
                else:
                    return "ERROR"
            else:
                # 回退到原始方法
                pull_command = f"adb -s {self.device} pull {remote_path} {save_path}"
                result = self.execute_adb(pull_command, self.type)
                if result != "ERROR":
                    return save_path
        return result

    def get_xml(self, prefix, save_dir):
        remote_path = os.path.join(self.xml_dir, prefix + '.xml').replace(self.backslash, '/')
        local_path = os.path.join(save_dir, prefix + '.xml')
        dump_command = f"adb -s {self.device} shell uiautomator dump {remote_path}"
        pull_command = f"adb -s {self.device} pull {remote_path} {local_path}"

        def is_file_empty(file_path):
            return os.path.exists(file_path) and os.path.getsize(file_path) == 0

        for attempt in range(5):
            result = self.execute_adb(dump_command, self.type)
            if result == "ERROR":
                time.sleep(5)
                continue

            # 对于远程实例，使用增强的文件传输功能
            if hasattr(self.remote_instance, 'pull_file_from_device'):
                success = self.remote_instance.pull_file_from_device(remote_path, local_path)
                if success and not is_file_empty(local_path):
                    return local_path
            else:
                # 回退到原始方法
                result = self.execute_adb(pull_command, self.type)
                if result != "ERROR" and not is_file_empty(local_path):
                    return local_path
            time.sleep(5)

        # Final attempt after 5 retries
        result = self.execute_adb(dump_command, self.type)
        
        # 对于远程实例，使用增强的文件传输功能
        if hasattr(self.remote_instance, 'pull_file_from_device'):
            success = self.remote_instance.pull_file_from_device(remote_path, local_path)
            if success and not is_file_empty(local_path):
                return local_path
        else:
            # 回退到原始方法
            result = self.execute_adb(pull_command, self.type)
            if result != "ERROR" and not is_file_empty(local_path):
                return local_path

        return result

    def get_ac_xml(self, prefix, save_dir):
        remote_path = f"{os.path.join(self.ac_xml_dir, 'ui.xml').replace(self.backslash, '/')}"
        local_path = os.path.join(save_dir, prefix + '.xml')
        pull_command = f"adb -s {self.device} pull {remote_path} {local_path}"

        def is_file_empty(file_path):
            return os.path.exists(file_path) and os.path.getsize(file_path) == 0

        for attempt in range(5):
            # 对于远程实例，使用增强的文件传输功能
            if hasattr(self.remote_instance, 'pull_file_from_device'):
                success = self.remote_instance.pull_file_from_device(remote_path, local_path)
                if success and not is_file_empty(local_path):
                    return local_path
            else:
                # 回退到原始方法
                result = self.execute_adb(pull_command, self.type)
                if result != "ERROR" and not is_file_empty(local_path):
                    return local_path
            time.sleep(5)

        # Final attempt after 5 retries
        # 对于远程实例，使用增强的文件传输功能
        if hasattr(self.remote_instance, 'pull_file_from_device'):
            success = self.remote_instance.pull_file_from_device(remote_path, local_path)
            if success and not is_file_empty(local_path):
                return local_path
        else:
            # 回退到原始方法
            result = self.execute_adb(pull_command, self.type)
            if result != "ERROR" and not is_file_empty(local_path):
                return local_path

        return result

    def get_current_activity(self):
        adb_command = "adb -s {device} shell dumpsys window | grep mCurrentFocus | awk -F '/' '{print $1}' | awk '{print $NF}'"
        adb_command = adb_command.replace("{device}", self.device)
        result = self.execute_adb(adb_command, self.type)
        if result != "ERROR":
            return result
        return 0

    def get_current_app(self):
        activity = self.get_current_activity()
        app = find_app(activity)
        return app

    def back(self):
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_BACK"
        ret = self.execute_adb(adb_command, self.type)
        return ret

    def enter(self):
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_ENTER"
        ret = self.execute_adb(adb_command, self.type)
        return ret

    def home(self):
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_HOME"
        ret = self.execute_adb(adb_command, self.type)
        return ret

    def tap(self, x, y):
        adb_command = f"adb -s {self.device} shell input tap {x} {y}"
        ret = self.execute_adb(adb_command, self.type)
        return ret

    def text(self, input_str):
        # adb_command = f'adb -s {self.device} input keyevent KEYCODE_MOVE_END'
        # ret = self.execute_adb(adb_command, self.type)
        adb_command = f'adb -s {self.device} shell input keyevent --press $(for i in {{1..100}}; do echo -n "67 "; done)'
        ret = self.execute_adb(adb_command, self.type)
        chars = input_str
        charsb64 = str(base64.b64encode(chars.encode('utf-8')))[1:]
        adb_command = f"adb -s {self.device} shell am broadcast -a ADB_INPUT_B64 --es msg {charsb64}"
        ret = self.execute_adb(adb_command, self.type)
        return ret

    def long_press(self, x, y, duration=1000):
        adb_command = f"adb -s {self.device} shell input swipe {x} {y} {x} {y} {duration}"
        ret = self.execute_adb(adb_command, self.type)
        return ret

    def kill_package(self, package_name):
        command = f"adb -s {self.device} shell am force-stop {package_name}"
        self.execute_adb(command, self.type)

    def swipe(self, x, y, direction, dist: Union[str, int] = "medium", quick=False):
        if x == None:
            x = self.width // 2
        if y == None:
            y = self.height // 2
        if isinstance(dist, str):
            unit_dist = int(self.width / 10)
            if dist == "long":
                unit_dist *= 10
            elif dist == "medium":
                unit_dist *= 2
        elif isinstance(dist, int):
            unit_dist = dist
        if direction == "up":
            offset = 0, -2 * unit_dist
        elif direction == "down":
            offset = 0, 2 * unit_dist
        elif direction == "left":
            offset = -1 * unit_dist, 0
        elif direction == "right":
            offset = unit_dist, 0
        else:
            return "ERROR"
        duration = 100 if quick else 400
        adb_command = f"adb -s {self.device} shell input swipe {x} {y} {x + offset[0]} {y + offset[1]} {duration}"
        ret = self.execute_adb(adb_command, self.type)
        return ret

    def swipe_precise(self, start, end, duration=400):
        start_x, start_y = start
        end_x, end_y = end
        adb_command = f"adb -s {self.device} shell input swipe {start_x} {start_x} {end_x} {end_y} {duration}"
        ret = self.execute_adb(adb_command, self.type)
        return ret

    def launch_app(self, package_name):
        command = f"adb -s {self.device} shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1"
        ret = self.execute_adb(command, self.type)
        return ret

    def start_screen_record(self, prefix):
        print("Starting screen record")
        command = f'adb -s {self.device} shell screenrecord /sdcard/{prefix}.mp4'
        return subprocess.Popen(command, shell=True)

    def launch(self, package_name):
        command = f"adb -s {self.device} shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1"
        self.execute_adb(command, self.type)

    def run_command(self, command):
        command = command.replace("adb", f"adb -s {self.device} ")
        return self.execute_adb(command, self.type)

    def check_ac_survive(self):
        try:
            time_command = f"adb -s {self.device} shell stat -c %y /sdcard/Android/data/com.example.android.xml_parser/files/ui.xml"
            time_phone_command = f"adb -s {self.device} shell date +\"%H:%M:%S\""
            result = time_within_ten_secs(self.execute_adb(time_command, self.type),
                                          self.execute_adb(time_phone_command, self.type))
        except Exception as e:
            print(e)
            return False
        return result


if __name__ == '__main__':
    
    class RemoteInstance:
        def execute_remote_adb_command(self, command):
            return {"result": "test_result"}
    
    And = AndroidController("emulator-5554", "remote", RemoteInstance())
    And.text("北京南站")
