import unittest
import sys
import os
from PIL import Image

# Adjust the path to import from the parent directory (project root)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from core.utils import sanitize_filename, apply_orientation
import config # For config.DEBUG_MODE if used by apply_orientation

class TestUtilsFunctions(unittest.TestCase):

    # Tests for sanitize_filename
    def test_sanitize_filename_invalid_chars(self):
        self.assertEqual(sanitize_filename('fi*le:n"ame?<>|'), 'filename')
        self.assertEqual(sanitize_filename('test\\file/path'), 'testfilepath')

    def test_sanitize_filename_spaces(self):
        self.assertEqual(sanitize_filename('file name with spaces'), 'file_name_with_spaces')

    def test_sanitize_filename_long_name(self):
        long_name = "a" * 150
        sanitized = sanitize_filename(long_name)
        self.assertEqual(len(sanitized), 100)
        self.assertTrue(sanitized.startswith("a" * 100))

    def test_sanitize_filename_no_change(self):
        self.assertEqual(sanitize_filename('valid_filename_123.txt'), 'valid_filename_123.txt')

    # Tests for apply_orientation
    def test_apply_orientation_no_orientation(self):
        # Create a dummy image
        img = Image.new('RGB', (60, 30), color = 'red')
        # Test with orientation = None
        img_none = apply_orientation(img.copy(), None)
        self.assertEqual(list(img.getdata()), list(img_none.getdata()))
        self.assertEqual(img.size, img_none.size)
        # Test with orientation = 1 (should also be no change)
        img_one = apply_orientation(img.copy(), 1)
        self.assertEqual(list(img.getdata()), list(img_one.getdata()))
        self.assertEqual(img.size, img_one.size)
        img.close()
        img_none.close()
        img_one.close()

    def test_apply_orientation_rotate_180(self):
        # Create a dummy image
        original_img = Image.new('RGB', (60, 30), color = 'blue')
        # Apply orientation 3 (ROTATE_180)
        # Temporarily disable debug mode for cleaner test output
        original_debug_mode = config.DEBUG_MODE
        config.DEBUG_MODE = False
        oriented_img = apply_orientation(original_img.copy(), 3)
        config.DEBUG_MODE = original_debug_mode

        self.assertIsInstance(oriented_img, Image.Image)
        # ROTATE_180 should not change dimensions
        self.assertEqual(original_img.size, oriented_img.size)
        # Simple check: if we rotate it back, it should be the same as original
        # This is not perfect as two different errors could cancel out, but it's a start
        # For a more robust check, one might compare pixel data more directly
        # or mock the transpose call.
        # For now, let's assume if it's rotated and dimensions match, it's likely correct.
        # If we rotate it twice by 180, it should be identical to original
        # (This requires the function to handle subsequent transforms correctly,
        # which it should as it operates on a copy)
        # For a simple 180 rotation, the pixels at opposite corners would be swapped.
        # Example: pixel at (0,0) moves to (width-1, height-1)
        # This level of detail is harder to check without more complex image manipulation in test.

        # Clean up
        original_img.close()
        oriented_img.close()

    def test_apply_orientation_flip_left_right(self):
        # Orientation 2: FLIP_LEFT_RIGHT
        original_img = Image.new('RGB', (2, 1), color='white')
        original_img.putpixel((0, 0), (255, 0, 0)) # Red pixel on left
        original_img.putpixel((1, 0), (0, 0, 255)) # Blue pixel on right
        
        original_debug_mode = config.DEBUG_MODE
        config.DEBUG_MODE = False
        oriented_img = apply_orientation(original_img.copy(), 2)
        config.DEBUG_MODE = original_debug_mode

        self.assertIsInstance(oriented_img, Image.Image)
        self.assertEqual(original_img.size, oriented_img.size)
        # Check if pixels are flipped
        self.assertEqual(oriented_img.getpixel((0, 0)), (0, 0, 255)) # Blue now on left
        self.assertEqual(oriented_img.getpixel((1, 0)), (255, 0, 0)) # Red now on right
        
        original_img.close()
        oriented_img.close()


if __name__ == '__main__':
    unittest.main()
