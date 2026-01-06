# pylint: disable=line-too-long, function-name-too-long
# Copyright 2025 ModelBest Inc. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import time
from typing import Any, Optional
from uuid import uuid4

from verl.tools.base_tool import BaseTool
from verl.tools.schemas import OpenAIFunctionToolSchema

logger = logging.getLogger(__name__)


class DefaultTool(BaseTool):
    """A tool for smartphone screens."""

    async def create(self, instance_id: Optional[str] = None, **kwargs) -> str:
        """Create a tool instance for controlling an Android device."""
        if instance_id is None:
            instance_id = str(uuid4())

        # Extract MobileSession from kwargs
        mobile_session = kwargs['create_kwargs'].get("mobile_session")
        accessibility = kwargs['create_kwargs'].get("accessibility", False)

        if not mobile_session:
            raise ValueError("Missing required MobileSession object")

        if not mobile_session.is_ready():
            raise ValueError("MobileSession is not ready - all components must be initialized")

        self._instance_dict[instance_id] = {
            "mobile_session": mobile_session,
            "accessibility": accessibility,
        }

        return instance_id


COORDINATES_PARAMS = {
    "type": "object",
    "properties": {
        "x1": {
            "type": "integer",
            "description": "The x-coordinate of the top-left corner of the rectangle."
        },
        "y1": {
            "type": "integer",
            "description": "The y-coordinate of the top-left corner of the rectangle."
        },
        "x2": {
            "type": "integer",
            "description": "The x-coordinate of the bottom-right corner of the rectangle."
        },
        "y2": {
            "type": "integer",
            "description": "The y-coordinate of the bottom-right corner of the rectangle."
        }
    },
    "required": ["x1", "y1", "x2", "y2"],
}


class TapTool(DefaultTool):
    """A tool for tapping UI elements on smartphone screens."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "tap",
                    "description": (
                        "This function is used to tap a UI element shown on the smartphone screen by simulating "
                        "a tap action within the specified rectangular area defined by the coordinates (x1, y1) "
                        "and (x2, y2). A simple use case is tap(462,1693,619,1870), which taps the center of the "
                        "UI element, calculated to be at [540.5,1781.5]. Return a string that contains the latest "
                        "XML of the current screen."
                    ),
                    "parameters": COORDINATES_PARAMS,
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute tap action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            x1 = parameters.get("x1")
            y1 = parameters.get("y1")
            x2 = parameters.get("x2")
            y2 = parameters.get("y2")

            if any(coord is None for coord in [x1, y1, x2, y2]):
                return "Error: Missing required coordinates", -0.5, {"success": False}

            element = [x1, y1, x2, y2]
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute tap action
            executor.do("Tap", element)
            time.sleep(1.0)
            recorder.update_after(executor.current_return, f"do(action='Tap', element={element})")
            recorder.turn_number += 1
            time.sleep(5)  # Wait for the tap action to complete
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()

            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing tap action: {e}")
            return f"Error executing tap action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class TypeTool(DefaultTool):
    """A tool for typing text on smartphone screens."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "type",
                    "description": (
                        "This function is used to insert text input in an input field/box. text_input is the "
                        "string you want to insert and must be wrapped with double quotation marks. A simple "
                        "use case can be type(\"Hello, world!\"), which inserts the string \"Hello, world!\" "
                        "into the input area on the smartphone screen. This function is only callable when you "
                        "see a keyboard showing in the lower half of the screen. Return a string that contains "
                        "the latest XML of the current screen."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text_input": {
                                "type": "string",
                                "description": "The text string to input using the keyboard."
                            }
                        },
                        "required": ["text_input"],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute type action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            text_input = parameters.get("text_input")
            if text_input is None:
                return "Error: Missing text_input parameter", -0.5, {"success": False}

            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute type action
            executor.do("Type", text=text_input)
            time.sleep(1.0)
            recorder.update_after(executor.current_return, f"do('action='Type', text='{text_input}')")
            recorder.turn_number += 1
            time.sleep(5)  # Wait for the type action to complete
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()

            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing type action: {e}")
            return f"Error executing type action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class LongPressTool(DefaultTool):
    """A tool for long pressing UI elements on smartphone screens."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "long_press",
                    "description": (
                        "This function is used to long press a UI element shown on the smartphone screen. "
                        "The element is identified by the rectangular area defined by the coordinates (x1, y1) "
                        "and (x2, y2). The function calculates the center of this area and performs a long press "
                        "action at that point. A simple use case can be long_press(462,1693,619,1870), which "
                        "long presses the UI element labeled on [540.5,1781.5]. Return a string that contains "
                        "the latest XML of the current screen."
                    ),
                    "parameters": COORDINATES_PARAMS,
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute long press action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            x1 = parameters.get("x1")
            y1 = parameters.get("y1")
            x2 = parameters.get("x2")
            y2 = parameters.get("y2")

            if any(coord is None for coord in [x1, y1, x2, y2]):
                return "Error: Missing required coordinates", -0.5, {"success": False}

            element = [x1, y1, x2, y2]
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute long press action
            executor.do("Long Press", element)
            time.sleep(1.0)
            recorder.update_after(executor.current_return, f"do('action='Long Press', element={element})")
            recorder.turn_number += 1
            time.sleep(5)  # Wait for the long press action to complete
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()

            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing long press action: {e}")
            return f"Error executing long press action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class SwipeTool(DefaultTool):
    """A tool for swiping on smartphone screens."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "swipe",
                    "description": (
                        "This function simulates a swipe gesture on a smartphone screen, which can be applied "
                        "to UI elements like scroll views or slide bars. The swipe starts from the center of a "
                        "rectangular area defined by (x1, y1) and (x2, y2), then moves in a specified direction "
                        "for a certain distance. Return a string that contains the latest XML of the current screen."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "x1": {
                                "type": "integer",
                                "description": "The x-coordinate of the top-left corner of the rectangle."
                            },
                            "y1": {
                                "type": "integer",
                                "description": "The y-coordinate of the top-left corner of the rectangle."
                            },
                            "x2": {
                                "type": "integer",
                                "description": "The x-coordinate of the bottom-right corner of the rectangle."
                            },
                            "y2": {
                                "type": "integer",
                                "description": "The y-coordinate of the bottom-right corner of the rectangle."
                            },
                            "direction": {
                                "type": "string",
                                "description": "The direction of the swipe (\"up\", \"down\", \"left\", \"right\")."
                            },
                            "dist": {
                                "type": "string",
                                "description": "The distance of the swipe, with options \"long\", \"medium\", \"short\". Defaults to \"medium\"."
                                
                            }
                        },
                        "required": ["x1", "y1", "x2", "y2", "direction", "dist"],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute swipe action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            x1 = parameters.get("x1")
            y1 = parameters.get("y1")
            x2 = parameters.get("x2")
            y2 = parameters.get("y2")
            direction = parameters.get("direction")
            dist = parameters.get("dist")

            if any(coord is None for coord in [x1, y1, x2, y2]) or not direction or not dist:
                return "Error: Missing required parameters", -0.5, {"success": False}

            element = [x1, y1, x2, y2]
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute swipe action
            executor.do("Swipe", element, direction=direction, dist=dist)
            time.sleep(1.0)
            recorder.update_after(executor.current_return, f"do('action='Swipe', element={element}, direction='{direction}', dist='{dist}')")
            recorder.turn_number += 1
            time.sleep(5)  # Wait for the swipe action to complete
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()

            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing swipe action: {e}")
            return f"Error executing swipe action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class BackTool(DefaultTool):
    """A tool for pressing the back button on smartphone screens."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "back",
                    "description": (
                        "Simulates a back button press. This method navigates the user back to the "
                        "previous screen or state in the application or operating system. Return a string that "
                        "contains the latest XML of the current screen."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute back action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute back action
            executor.do("Back")
            time.sleep(1.0)
            recorder.update_after(executor.current_return, "do('action='Back')")
            recorder.turn_number += 1
            time.sleep(5)  # Wait for the back action to complete
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()
            
            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing back action: {e}")
            return f"Error executing back action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class HomeTool(DefaultTool):
    """A tool for pressing the home button on smartphone screens."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "home",
                    "description": (
                        "Simulates pressing the home button. This method takes the user to the home "
                        "screen of the device, minimizing the current application or context. It\'s akin to exiting "
                        "the current state and returning to the main dashboard or operating system\'s primary "
                        "interface. Return a string that contains the latest XML of the current screen."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute home action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute home action
            executor.do("Home")
            time.sleep(1.0)
            recorder.update_after(executor.current_return, "do('action='Home')")
            recorder.turn_number += 1
            time.sleep(5)  # Wait for the home action to complete
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()

            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing home action: {e}")
            return f"Error executing home action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class SubmitTool(DefaultTool):
    """A tool for submitting evidences when completing a task."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "submit",
                    "description": "Submit the evidences when completes the task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "A message to print before exiting."
                            }, 
                            "evidences": {
                                "type": "array",
                                "items": {
                                    "type": "integer"
                                },
                                "description": (
                                    "A list of integers representing the IDs of the decisive evidence "
                                    "steps that led to the successful completion of the task. If the task "
                                    "was not completed successfully, this list can be empty. An individual "
                                    "piece of evidence is a **Tool Call**. This includes its unique ID, "
                                    "its input parameters, and its output result. Each tool call is assigned "
                                    "a unique number `x`, formatted as `[TOOL CALL ID: x]`"
                                )
                            }
                        },
                        "required": ["message", "evidences"],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute submit action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            message = parameters.get("message", None)
            evidences = parameters.get("evidences", [])
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute submit action
            executor.finish(message, evidences)
            recorder.update_after(executor.current_return, f"do('action='finish', message='{message}', evidences={evidences})")
            recorder.turn_number += 1
            time.sleep(1.0)  # Wait for the submit action to complete
            return f"Task Complete. Your Message is {message} and Your Submitted Evidences are {evidences}\n**PLEASE STOP CALLING ANY TOOL NOW AND OUTPUT THE ANSWER.**", 1.0, {"success": True, "completed": True}

        except Exception as e:
            logger.error(f"Error executing submit action: {e}")
            return f"Error executing submit action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class WaitTool(DefaultTool):
    """A tool for waiting specified amount of time."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "wait",
                    "description": (
                        "This function is used to wait for a specified amount of time (in seconds). "
                        "It can be useful when waiting for UI elements to load or animations to complete."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "seconds": {
                                "type": "number",
                                "description": "The number of seconds to wait."
                            }
                        },
                        "required": ["seconds"],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute wait action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            seconds = int(parameters.get("seconds", 5.0))
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute wait action
            executor.do("Wait", seconds=seconds)
            time.sleep(1.0)
            recorder.update_after("wait_completed", f"do('action='Wait', seconds={seconds})")
            recorder.turn_number += 1
            time.sleep(5)
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()
            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing wait action: {e}")
            return f"Error executing wait action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class EnterTool(DefaultTool):
    """A tool for pressing the Enter key."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "enter",
                    "description": (
                        "This function is used to press the Enter key on the smartphone. It simulates "
                        "pressing the Enter key and returns the latest XML of the current screen "
                        "after the action completes."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute enter action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute enter action
            executor.do("Enter")
            time.sleep(1.0)
            recorder.update_after(executor.current_return, "do('action='Enter')")
            recorder.turn_number += 1
            time.sleep(5)  # Wait for the enter action to complete
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()
            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing enter action: {e}")
            return f"Error executing enter action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class LaunchTool(DefaultTool):
    """A tool for launching applications on smartphone screens."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "launch",
                    "description": (
                        "Launches a specified application on the device."
                        "The app parameter should be the name of the application to launch. Return a string that contains the latest XML of the current screen."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "app": {
                                "type": "string",
                                "description": 'The name of the application to launch (e.g., "Chrome", "Calculator", "Settings").'
                            }
                        },
                        "required": ["app"],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute launch action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            app = parameters.get("app")
            if not app:
                return "Error: Missing app parameter", -0.5, {"success": False}

            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            executor = mobile_session.page_executor
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Execute launch action
            executor.do("Launch", app=app)
            time.sleep(1.0)
            recorder.update_after(executor.current_return, f"do('action='Launch', app='{app}')")
            recorder.turn_number += 1
            time.sleep(5)  # Wait for the application to launch
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()

            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error executing launch action: {e}")
            return f"Error executing launch action: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]


class GetCurrentXMLTool(DefaultTool):
    """A tool for getting the current XML representation of the smartphone screen."""

    def __init__(self, config: dict, tool_schema: Optional[OpenAIFunctionToolSchema] = None):
        if tool_schema is None:
            tool_schema = OpenAIFunctionToolSchema.model_validate({
                "type": "function",
                "function": {
                    "name": "get_current_xml",
                    "description": (
                        "This function is used to get the current XML representation of the smartphone screen "
                        "without performing any action. It returns the latest XML of the current screen state."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                }
            })
        super().__init__(config, tool_schema)
        self._instance_dict = {}

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[str, float, dict]:
        """Execute get current XML action on the Android device."""
        instance_data = self._instance_dict.get(instance_id)
        if not instance_data:
            return "Error: Invalid instance_id", -1.0, {"success": False}
        if type(parameters) is str:
            try:
                parameters = json.loads(parameters)
            except:
                print(f"🚨 string format {parameters=} cannot be loaded as dict!")
                parameters = {}
        try:
            mobile_session = instance_data["mobile_session"]
            accessibility = instance_data["accessibility"]
            
            # Get components from mobile_session
            controller = mobile_session.controller
            recorder = mobile_session.recorder

            # Get current XML
            recorder.update_before(controller=controller, need_screenshot=True, ac_status=accessibility)
            compressed_xml_json = recorder.get_latest_xml()

            return compressed_xml_json, 0.0, {"success": True}

        except Exception as e:
            logger.error(f"Error getting current XML: {e}")
            return f"Error getting current XML: {e}", -1.0, {"success": False}

    async def release(self, instance_id: str, **kwargs) -> None:
        """Release the tool instance."""
        if instance_id in self._instance_dict:
            del self._instance_dict[instance_id]
