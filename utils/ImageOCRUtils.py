import difflib
from typing import List
from loguru import logger

from paddleocr import PaddleOCR


class ImageOCRUtils(object):
    # Util Class for Image or OCR handling
    def __init__(self, lang: str = None) -> None:
        """ Initialization for ImageOCRUtils

        Args:
            lang, str: specification for the detection language
        """
        if lang is None:
            self._ocr = PaddleOCR(use_angle_cls=True)
        else:
            self._ocr = PaddleOCR(use_angle_cls=True, lang=lang)

    def _get_image_str_list(self, image_path: str) -> List[str]:
        """ Get the string from image using OCR method

        Args:
            image_path, str: the image path

        Returns:
            List[str], return the string list from OCR
        """
        ret_list: List[str] = []
        result: list = self._ocr.ocr(image_path, cls=True)
        result: list = result[0] if len(result) > 0 else None
        if result:
            ret_list = [line[1][0].strip() for line in result]
        return ret_list

    def get_image_str_list(self, image_path: str) -> List[str]:
        return self._get_image_str_list(image_path)

    def _diff_two_images(self, former_image: str, latter_image: str) -> List[str]:
        """ Differ two images using OCR

        Args:
            former_image, str: former image path
            latter_image, str: latter image path

        Returns:
            List[str], Return the new strings in latter image
        """
        diff_list: List[str] = []
        try:
            before_text_list: List[str] = self.get_image_str_list(former_image)
            after_text_list: List[str] = self.get_image_str_list(latter_image)
            d = difflib.Differ()
            diff = d.compare(before_text_list, after_text_list)
            for diff_info in diff:
                if diff_info.startswith("+"):
                    diff_info = diff_info[1:].strip()
                    if diff_info != "":
                        diff_list.append(diff_info)
        except Exception as e:
            logger.error(f"Something bad when differing two images {e}")
        finally:
            return diff_list

    def diff_two_images(self, before_image: str, after_image: str) -> List[str]:
        return self._diff_two_images(before_image, after_image)
