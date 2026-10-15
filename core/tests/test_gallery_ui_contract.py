"""Static assertions for frontend gallery changes (browser runtime requires Brave)."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class GalleryUIContractTests(unittest.TestCase):
    def test_publisher_uses_model_name_not_native_prompt(self):
        controller=(ROOT/'static/studio.js').read_text()
        frontend=(ROOT/'static/rantlist.js').read_text()
        self.assertIn('publish(model.id,model.name)',controller)
        self.assertNotIn('prompt(',frontend)
        self.assertIn('rantlistPublishName',frontend)
        self.assertIn('Published successfully',frontend)
        self.assertIn('Upload failed:',frontend)
    def test_gallery_resizes_and_limits_visible_thumbnail_loads(self):
        markup=(ROOT/'templates/index.html').read_text()
        js=(ROOT/'static/studio.js').read_text()
        gallery=(ROOT/'static/rantlist.js').read_text()
        css=(ROOT/'static/studio.css').read_text()
        self.assertIn('libraryResizeHandle',markup)
        self.assertIn('setPointerCapture',js)
        self.assertIn('ArrowUp',js)
        self.assertIn('grid-auto-rows',css)
        self.assertIn('IntersectionObserver',gallery)
        self.assertIn('previewActive<3',gallery)
        self.assertIn('Preview unavailable',gallery)
if __name__=='__main__':unittest.main()
