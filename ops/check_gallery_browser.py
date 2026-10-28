#!/usr/bin/env python3
"""Optional visual-geometry regression: system Chromium/Playwright, no Flask/network."""
from pathlib import Path
from tempfile import TemporaryDirectory
from shutil import which
from os import environ
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT/'core/static/studio.css').read_text()
BROWSER=environ.get('MIXAMO_LAYOUT_BROWSER') or which('chromium') or which('google-chrome')
if not BROWSER: raise SystemExit('Set MIXAMO_LAYOUT_BROWSER to a headless Chromium binary to run this optional check.')
with TemporaryDirectory() as tmp:
    pagefile=Path(tmp)/'gallery.html'
    cards=''.join('<article class="model-card"><button class="model-card-main"><div class="model-thumb"><img src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'30\' height=\'90\'%3E%3Crect width=\'30\' height=\'90\' fill=\'coral\'/%3E%3C/svg%3E"></div><div class="model-card-label"><strong>Test model</strong></div></button><div class="model-card-actions"><button>◈</button><button>↑ R</button><button>↓</button><button>×</button></div></article>' for _ in range(40))
    pagefile.write_text(f'''<!doctype html><html><head><style>{CSS}</style><style>
    body{{margin:0;background:#111}}#stage{{width:1000px;height:900px;position:relative}}
    </style></head><body><div id="stage"><section class="library-dock" id="libraryDock" style="--library-height:650px">
    <div class="library-head">MODEL LIBRARY</div><div class="library-cards" id="rantlistCards">{cards}</div></section></div></body></html>''')
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=BROWSER,headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1100,'height':960})
        page.set_content(pagefile.read_text())
        for width in (112,164,228):
            for ratio in ('1 / 1','2 / 3','3 / 2'):
                for height in (250,650):
                    page.evaluate('''({width,ratio,height})=>{
                      const dock=document.getElementById('libraryDock');
                      dock.dataset.gallerySize=width===112?'s':width===164?'m':'xl';
                      dock.style.setProperty('--card-width',`${width}px`);
                      dock.style.setProperty('--card-ratio',ratio);
                      dock.style.setProperty('--library-height',`${height}px`);
                    }''', {'width':width,'ratio':ratio,'height':height})
                    bad=page.evaluate('''()=>{
                        const cards=Array.from(document.querySelectorAll('.model-card'));
                        const rects=cards.map(c=>c.getBoundingClientRect());
                        const violations=[];
                        for(let i=0;i<rects.length;i++){
                          const r=rects[i];
                          if(r.width<10||r.height<10)violations.push(`empty ${i}`);
                          for(let j=0;j<i;j++){
                            const t=rects[j];
                            if(Math.min(r.right,t.right)-Math.max(r.left,t.left)>0.5 &&
                               Math.min(r.bottom,t.bottom)-Math.max(r.top,t.top)>0.5)
                              violations.push(`overlap ${j}/${i}`);
                          }
                          for(const item of cards[i].querySelectorAll('.model-thumb,.model-thumb img,.model-card-label,.model-card-actions')){
                            const q=item.getBoundingClientRect();
                            if(q.left<r.left-1||q.right>r.right+1||q.top<r.top-1||q.bottom>r.bottom+1)
                              violations.push(`overflow ${i} ${item.className}`);
                          }
                        }
                        return violations;
                      }''')
                    
                    assert not bad,(width,ratio,height,bad[:10])
        browser.close()
print('PASS: 18 card size/ratio/panel-height layouts, 40 cards each; no overlap or overflow')
