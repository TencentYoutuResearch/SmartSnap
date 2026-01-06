# pylint: disable=line-too-long, function-name-too-long

import inspect
import json
import re
import time
import os
import glob
from functools import partial
from PIL import Image, ImageDraw, ImageFont
from ..templates.packages import find_package
from .utils import call_dino, plot_bbox, get_center_width_height


def remove_leading_zeros_in_string(s):
    # 使用正则表达式匹配列表中的每个数值并去除前导零
    return re.sub(r'\b0+(\d)', r'\1', s)


class TextOnlyExecutor:
    def __init__(self, controller, config):
        self.config = config
        self.controller = controller
        self.device = controller.device
        self.screenshot_dir = config.get('screenshot_dir', './screenshots')
        self.task_id = int(time.time())

        self.new_page_captured = False
        self.current_screenshot = None
        self.current_return = None

        self.last_turn_element = None
        self.last_turn_element_tagname = None
        self.is_finish = False
        self.device_pixel_ratio = None
        self.latest_xml = None
        
        self.finish_message = None
        self.submit_evidences = None
        # self.glm4_key = config.glm4_key

        # self.device_pixel_ratio = self.page.evaluate("window.devicePixelRatio")

    def __get_current_status__(self):
        page_position = None
        scroll_height = None
        status = {
            "Current URL": self.controller.get_current_activity(),
        }
        return json.dumps(status, ensure_ascii=False)

    def modify_relative_bbox(self, relative_bbox):
        viewport_width, viewport_height = self.controller.viewport_size
        modify_x1 = relative_bbox[0] * viewport_width / 1000
        modify_y1 = relative_bbox[1] * viewport_height / 1000
        modify_x2 = relative_bbox[2] * viewport_width / 1000
        modify_y2 = relative_bbox[3] * viewport_height / 1000
        return [modify_x1, modify_y1, modify_x2, modify_y2]

    def __call__(self, code_snippet):
        '''
        self.new_page_captured = False
        self.controller.on("page", self.__capture_new_page__)
        self.current_return = None'''

        local_context = self.__get_class_methods__()
        local_context.update(**{'self': self})
        print(code_snippet.strip())
        if len(code_snippet.split("\n")) > 1:
            for code in code_snippet.split("\n"):
                if "Action: " in code:
                    code_snippet = code
                    break

        code = remove_leading_zeros_in_string(code_snippet.strip())
        exec(code, {}, local_context)
        return self.current_return

    def __get_class_methods__(self, include_dunder=False, exclude_inherited=True):
        """
        Returns a dictionary of {method_name: method_object} for all methods in the given class.

        Parameters:
        - cls: The class object to inspect.
        - include_dunder (bool): Whether to include dunder (double underscore) methods.
        - exclude_inherited (bool): Whether to exclude methods inherited from parent classes.
        """
        methods_dict = {}
        cls = self.__class__
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if exclude_inherited and method.__qualname__.split('.')[0] != cls.__name__:
                continue
            if not include_dunder and name.startswith('__'):
                continue
            methods_dict[name] = partial(method, self)
        return methods_dict

    def update_screenshot(self, prefix=None, suffix=None):
        # time.sleep(2)
        if prefix is None and suffix is None:
            self.current_screenshot = f"{self.screenshot_dir}/screenshot-{time.time()}.png"
        elif prefix is not None and suffix is None:
            self.current_screenshot = f"{self.screenshot_dir}/screenshot-{prefix}-{time.time()}.png"
        elif prefix is None and suffix is not None:
            self.current_screenshot = f"{self.screenshot_dir}/screenshot-{time.time()}-{suffix}.png"
        else:
            self.current_screenshot = f"{self.screenshot_dir}/screenshot-{prefix}-{time.time()}-{suffix}.png"
        self.controller.save_screenshot(self.current_screenshot)

    def _wrap_text(self, text, font, max_width):
        """
        文本自动换行函数
        """
        lines = []
        words = text.split(' ')
        current_line = ""
        
        for word in words:
            # 测试当前行加上新单词的宽度
            test_line = current_line + (" " if current_line else "") + word
            bbox = font.getbbox(test_line)
            test_width = bbox[2] - bbox[0]
            
            if test_width <= max_width:
                current_line = test_line
            else:
                # 如果当前行不为空，将其添加到结果中
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    # 如果单个单词就超过最大宽度，强制换行
                    lines.append(word)
        
        # 添加最后一行
        if current_line:
            lines.append(current_line)
        
        return lines

    def _draw_multiline_text(self, draw, text, font, max_width, start_x, start_y, fill_color, bg_color=None, padding=10):
        """
        绘制多行文本
        """
        lines = self._wrap_text(text, font, max_width)
        line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + 5  # 行高加上行间距
        total_height = len(lines) * line_height
        
        # 计算最大行宽
        max_line_width = 0
        for line in lines:
            bbox = font.getbbox(line)
            line_width = bbox[2] - bbox[0]
            max_line_width = max(max_line_width, line_width)
        
        # 绘制背景
        if bg_color:
            bg_box = [
                start_x - padding,
                start_y - padding,
                start_x + max_line_width + padding,
                start_y + total_height + padding
            ]
            draw.rectangle(bg_box, fill=bg_color)
        
        # 绘制每一行文本
        for i, line in enumerate(lines):
            y_pos = start_y + i * line_height
            draw.text((start_x, y_pos), line, fill=fill_color, font=font)
        
        return max_line_width, total_height

    def compose_GIF(self, task_instruction: str):
        """
        将截图目录中的截图文件合并成GIF动画
        """
        finish_message = self.finish_message
        try:
            # 获取所有截图文件
            screenshot_pattern = os.path.join(self.screenshot_dir, "screenshot-*.png")
            screenshot_files = glob.glob(screenshot_pattern)
            
            if len(screenshot_files) < 3:
                print("截图文件数量不足，无法生成GIF")
                return None
            
            # 按文件名中的时间戳排序
            screenshot_files.sort(key=lambda x: os.path.getctime(x))
            screenshot_files = screenshot_files[1:]
            
            # 打开所有图片并添加帧编号
            images = []
            durations = []  # 存储每帧的持续时间
            
            for i, file_path in enumerate(screenshot_files, 1):
                try:
                    img = Image.open(file_path)
                    # 转换为RGB模式以确保兼容性
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # 在图片上添加帧编号
                    draw = ImageDraw.Draw(img)
                    
                    # 设置文本样式
                    frame_text = f"Frame {i}"
                    try:
                        # 尝试使用系统字体
                        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
                        finish_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
                    except:
                        # 如果系统字体不可用，使用默认字体
                        font = ImageFont.load_default()
                        finish_font = ImageFont.load_default()
                    
                    # 获取文本大小
                    text_bbox = draw.textbbox((0, 0), frame_text, font=font)
                    text_width = text_bbox[2] - text_bbox[0]
                    text_height = text_bbox[3] - text_bbox[1]
                    
                    # 在图片右上角添加帧编号
                    x = img.width - text_width - 20
                    y = 20
                    
                    # 添加半透明背景
                    background_box = [x-10, y-5, x+text_width+10, y+text_height+5]
                    draw.rectangle(background_box, fill=(0, 0, 0, 128))
                    
                    # 添加白色文本
                    draw.text((x, y), frame_text, fill=(255, 255, 255), font=font)
                    
                    # 在每一帧的页面上部绘制任务指令
                    if task_instruction:
                        instruction_text = f"Task: {task_instruction}"
                        
                        # 计算可用宽度（图片宽度的85%）
                        max_instruction_width = int(img.width * 0.85)
                        
                        # 使用多行文本绘制函数绘制任务指令
                        instruction_x = (img.width - max_instruction_width) // 2
                        instruction_y = 20  # 从顶部向下20像素开始
                        
                        self._draw_multiline_text(
                            draw, instruction_text, finish_font, max_instruction_width,
                            instruction_x, instruction_y, (255, 255, 255), (0, 0, 0, 180), 20
                        )
                    
                    # 如果是最后一帧且有finish_message，添加完成消息
                    is_last_frame = (i == len(screenshot_files))
                    if is_last_frame and finish_message:
                        # 在图片中央下方添加完成消息
                        finish_text = f"Task Finish: {finish_message}"
                        
                        # 计算可用宽度（图片宽度的80%）
                        max_text_width = int(img.width * 0.8)
                        
                        # 使用多行文本绘制函数
                        temp_x = (img.width - max_text_width) // 2
                        temp_y = img.height - 120  # 从底部向上120像素开始
                        
                        text_width, text_height = self._draw_multiline_text(
                            draw, finish_text, finish_font, max_text_width,
                            temp_x, temp_y, (255, 255, 255), (0, 128, 0, 180), 20
                        )
                        
                        # 最后一帧持续时间更长
                        durations.append(3000)  # 3秒
                    else:
                        durations.append(1000)  # 普通帧1秒
                    
                    images.append(img)
                except Exception as e:
                    print(f"无法打开图片 {file_path}: {e}")
                    continue
            
            if len(images) < 2:
                print("有效截图数量不足，无法生成GIF")
                return None
            
            # 生成GIF文件名
            gif_filename = f"{self.screenshot_dir}/task_{self.task_id}_animation.gif"
            
            # 保存为GIF，使用不同的持续时间
            images[0].save(
                gif_filename,
                save_all=True,
                append_images=images[1:],
                duration=durations,  # 使用变长的持续时间列表
                loop=0  # 无限循环
            )
            
            print(f"GIF动画已保存到: {gif_filename}")
            return gif_filename
            
        except Exception as e:
            print(f"生成GIF时发生错误: {e}")
            return None

    def do(self, action=None, element=None, **kwargs):
        assert action in ["Tap", "Type", "Swipe", "Enter", "Home", "Back", "Long Press", "Wait", "Launch",
                          "Call_API"], "Unsupported Action"
        if self.config.get('is_relative_bbox', False):
            if element is not None:
                element = self.modify_relative_bbox(element)
        if action == "Tap":
            self.tap(element)
        elif action == "Type":
            self.type(**kwargs)
        elif action == "Swipe":
            self.swipe(element, **kwargs)
        elif action == "Enter":
            self.press_enter()
        elif action == "Home":
            self.press_home()
        elif action == "Back":
            self.press_back()
        elif action == "Long Press":
            self.long_press(element)
        elif action == "Wait":
            self.wait()
        elif action == "Launch":
            self.launch(**kwargs)
        elif action == "Call_API":
            self.call_api(**kwargs)
        else:
            raise NotImplementedError()
        # self.__update_screenshot__() # update screenshot 全部移到recoder内

    def get_relative_bbox_center(self, instruction, screenshot):
        # 获取相对 bbox
        relative_bbox = call_dino(instruction, screenshot)

        viewport_width, viewport_height = self.controller.get_device_size()
        center_x, center_y, width_x, height_y = get_center_width_height(relative_bbox, viewport_width, viewport_height)

        # 点击计算出的中心点坐标
        # print(center_x, center_y)
        plot_bbox([int(center_x - width_x / 2), int(center_y - height_y / 2), int(width_x), int(height_y)], screenshot,
                  instruction)

        return (int(center_x), int(center_y)), relative_bbox

    def tap(self, element):
        if isinstance(element, list) and len(element) == 4:
            center_x = (element[0] + element[2]) / 2
            center_y = (element[1] + element[3]) / 2
        elif isinstance(element, list) and len(element) == 2:
            center_x, center_y = element
        else:
            raise ValueError("Invalid element format")
        self.controller.tap(center_x, center_y)
        self.current_return = {"operation": "do", "action": 'Tap', "kwargs": {"element": element}}

    def long_press(self, element):
        if isinstance(element, list) and len(element) == 4:
            center_x = (element[0] + element[2]) / 2
            center_y = (element[1] + element[3]) / 2
        elif isinstance(element, list) and len(element) == 2:
            center_x, center_y = element
        else:
            raise ValueError("Invalid element format")
        self.controller.long_press(center_x, center_y)
        self.current_return = {"operation": "do", "action": 'Long Press', "kwargs": {"element": element}}

    def swipe(self, element=None, **kwargs):
        if element is None:
            center_x, center_y = self.controller.width // 2, self.controller.height // 2
        elif element is not None:
            if isinstance(element, list) and len(element) == 4:
                center_x = (element[0] + element[2]) / 2
                center_y = (element[1] + element[3]) / 2
            elif isinstance(element, list) and len(element) == 2:
                center_x, center_y = element
            else:
                raise ValueError("Invalid element format")
        assert "direction" in kwargs, "direction is required for swipe"
        direction = kwargs.get("direction")
        dist = kwargs.get("dist", "medium")
        self.controller.swipe(center_x, center_y, direction, dist)
        self.current_return = {"operation": "do", "action": 'Swipe',
                               "kwargs": {"element": element, "direction": direction, "dist": dist}}
        time.sleep(1)

    def type(self, **kwargs):
        assert "text" in kwargs, "text is required for type"
        instruction = kwargs.get("text")
        self.controller.text(instruction)
        self.controller.enter()
        self.current_return = {"operation": "do", "action": 'Type',
                               "kwargs": {"text": instruction}}

    def press_enter(self):
        self.controller.enter()
        self.current_return = {"operation": "do", "action": 'Press Enter'}

    def press_back(self):
        self.controller.back()
        self.current_return = {"operation": "do", "action": 'Press Back'}

    def press_home(self):
        self.controller.home()
        self.current_return = {"operation": "do", "action": 'Press Home'}

    def finish(self, message=None, evidences=None):
        self.finish_message = message
        self.submit_evidences = evidences 
        self.is_finish = True
        self.current_return = {"operation": "finish", "action": 'finish', "kwargs": {"message": message}}

    def wait(self):
        time.sleep(5)
        self.current_return = {"operation": "do", "action": 'Wait'}

    def launch(self, **kwargs):
        assert "app" in kwargs, "app is required for launch"
        app = kwargs.get("app")
        try:
            package = find_package(app)
        except:
            import traceback
            traceback.print_exc()
        self.controller.launch_app(package)
        self.current_return = {"operation": "do", "action": 'Launch',
                               "kwargs": {"package": package}}

    '''
    def call_api(self, **kwargs):
        assert "instruction" in kwargs, "instruction is required for call_api"
        glm4_template = "你需要根据以下化简版本的XML数据,对提问进行回答。你需要直接回答问题。\n\nXML数据：\n\n{xml_compression}\n\n提问:{question}\n\n提示：你的输出应当不超过100字"
        instruction = kwargs.get("instruction")
        if kwargs.get("with_screen_info"):
            with_screen_info = kwargs.get("with_screen_info")
        else:
            with_screen_info = False
        if with_screen_info:
            prompt = glm4_template.format(xml_compression=self.latest_xml, question=instruction)
            response = get_completion_glm4(prompt, self.glm4_key)
            self.current_return = {"operation": "do", "action": 'Call_API',
                                   "kwargs": {"instruction": instruction, "response": response, "full_query": prompt,
                                              "with_screen_info": True}}
        else:
            response = get_completion_glm4(instruction, self.glm4_key)
            self.current_return = {"operation": "do", "action": 'Call_API',
                                   "kwargs": {"instruction": instruction, "response": response,
                                              "with_screen_info": False}}'''
