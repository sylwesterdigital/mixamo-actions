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
    def test_portrait_grid_rows_are_intrinsic_and_never_overlap(self):
        css=(ROOT/'static/studio.css').read_text()
        # A fixed row height smaller than a 2:3 XL card used to cause stacking
        # (XL=228px, portrait=342px, old row=146px).
        self.assertNotIn('grid-auto-rows:146px',css)
        self.assertNotIn('height:146px',css)
        self.assertIn('grid-auto-rows:max-content',css)
        self.assertIn('aspect-ratio:var(--card-ratio,2 / 3)',css)
        self.assertIn('overflow-y:auto',css)
    def test_thumbnail_is_transparent_portrait_and_restores_renderer(self):
        viewer=(ROOT/'static/viewer.mjs').read_text()
        self.assertIn('alpha:true',viewer)
        self.assertIn('const width=360,height=540',viewer)
        self.assertIn('scene.background=null',viewer)
        self.assertIn('floor.visible=false',viewer)
        self.assertIn('grid.visible=false',viewer)
        self.assertIn('setClearColor(0x000000,0)',viewer)
        self.assertIn('setFromObject(model)',viewer)
        self.assertIn('finally{',viewer)
        for restored in ('scene.background=previousBackground','floor.visible=previousFloor',
                         'grid.visible=previousGrid','renderer.setSize(previousSize.x,previousSize.y,false)'):
            self.assertIn(restored,viewer)
    def test_collector_is_downloadable_without_automatic_injection(self):
        backend=(ROOT/'flask_app.py').read_text()
        markup=(ROOT/'templates/index.html').read_text()
        collector=(ROOT/'mixamo_motion_collector.js').read_text()
        self.assertIn("@app.get('/collector.js')",backend)
        self.assertIn('href="/collector.js"',markup)
        self.assertIn('Mixamo Motion Collector',collector)
    def test_gallery_sizes_aspects_and_overlays_and_log_copy(self):
        markup=(ROOT/'templates/index.html').read_text()
        js=(ROOT/'static/studio.js').read_text()
        remote=(ROOT/'static/rantlist.js').read_text()
        css=(ROOT/'static/studio.css').read_text()
        for key in ('xl','m','s'): self.assertIn('data-gallery-size="'+key+'"',markup)
        for key in ('square','portrait','landscape'): self.assertIn('data-gallery-ratio="'+key+'"',markup)
        for name in ('copyConsole','downloadConsole'): self.assertIn(name,markup)
        self.assertIn('fullDiagnosticReport',js)
        self.assertIn('--card-ratio',css)
        self.assertIn('object-fit:contain',css)
        self.assertIn('model-card-label',css)
        self.assertNotIn('Stage avatar',remote)

if __name__=='__main__':unittest.main()
