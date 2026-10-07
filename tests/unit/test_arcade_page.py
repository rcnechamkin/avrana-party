"""Tier 1: the arcade phone page (arcade/index.html) as an Avrana game surface (AVR-133).

The page cannot load the Party's stylesheet (it may be served from the game's own origin, or over
plain HTTP, where /party/ does not exist), so it carries a copy of the design tokens and of the
icons it draws. These tests hold the copies equal to their sources, so the page cannot drift from
the shell without a failing test, and check the rules of docs/design/ACCESSIBILITY.md that a
stylesheet-free read of the file can prove. What needs a layout engine (target sizes, nothing
off screen, portrait and landscape) is in tests/offline/arcade.spec.ts; what needs a thumb is on
the AVR-133 pull request's "Needs real phones" list.
"""
import json
import re
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from avrana import REPO_ROOT

PAGE = (REPO_ROOT / 'arcade' / 'index.html').read_text(encoding='utf-8')
SHELL_CSS = (REPO_ROOT / 'web' / 'src' / 'party.css').read_text(encoding='utf-8')
SHELL_ICONS = (REPO_ROOT / 'web' / 'party' / 'lib' / 'icons.js').read_text(encoding='utf-8')
LUCIDE = REPO_ROOT / 'node_modules' / 'lucide-static' / 'icons'     # present after npm ci, as in CI

CONTRAST = re.compile(r'@media\s*\(prefers-contrast:\s*more\)\s*\{\s*:root\s*\{([^}]*)\}', re.S)
TOKEN = re.compile(r'(--(?:color|radius)-[a-z0-9-]+)\s*:\s*([^;]+);')


def tokens(css):
    """(base, contrast): the custom colour and radius properties, and the prefers-contrast override."""
    override = ' '.join(CONTRAST.findall(css))
    base = CONTRAST.sub('', css)
    squash = lambda text: {name: ' '.join(value.split()) for name, value in TOKEN.findall(text)}
    return squash(base), squash(override)


def page_style():
    return re.search(r'<style>(.*?)</style>', PAGE, re.S).group(1)


def page_script():
    return re.search(r'<script>\n(.*?)</script>', PAGE, re.S).group(1)


VOID = {'meta', 'link', 'br', 'img', 'input', 'hr'}


class Elements(HTMLParser):
    """The page's elements with their attributes and the text inside them (svg has none)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.stack = [], []
        self.feed(PAGE)

    def handle_starttag(self, tag, attrs):
        item = {'tag': tag, 'attrs': dict(attrs), 'text': ''}
        self.found.append(item)
        if tag not in VOID:
            self.stack.append(item)

    def handle_startendtag(self, tag, attrs):
        self.found.append({'tag': tag, 'attrs': dict(attrs), 'text': ''})

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1]['tag'] in ('style', 'script'):
            return
        for item in self.stack:
            item['text'] += data


def elements(tag):
    return [e for e in Elements().found if e['tag'] == tag]


class TokensFollowTheShell(unittest.TestCase):
    def test_every_colour_and_radius_is_the_shells(self):
        shell, shell_contrast = tokens(SHELL_CSS)
        mine, mine_contrast = tokens(page_style())
        self.assertGreater(len(mine), 15)
        for name, value in mine.items():
            self.assertIn(name, shell, f'{name} is not a token of web/src/party.css')
            self.assertEqual(value, shell[name], name)

    def test_more_contrast_is_asked_for_the_way_the_shell_asks(self):
        _, shell_contrast = tokens(SHELL_CSS)
        mine, mine_contrast = tokens(page_style())
        self.assertTrue(mine_contrast, 'the page honours prefers-contrast: more')
        for name, value in mine_contrast.items():
            self.assertEqual(value, shell_contrast.get(name), name)
        # a token the shell raises for more contrast and the page uses is raised here too
        css = page_style()
        for name in shell_contrast:
            if f'var({name}' in css:
                self.assertIn(name, mine_contrast, f'{name} is raised for more contrast in the shell')

    def test_every_token_the_page_uses_it_declares(self):
        css = page_style()
        mine, _ = tokens(css)
        for name in set(re.findall(r'var\((--(?:color|radius)-[a-z0-9-]+)', css)):
            self.assertIn(name, mine, name)
        for name in mine:
            self.assertIn(f'var({name}', css, f'{name} is declared and never used')


def sprite():
    """{name: [(tag, attributes)]} of the page's inline icons (<symbol id="i-name">)."""
    root = ET.fromstring(re.search(r'<svg class="sprite".*?</svg>', PAGE, re.S).group(0))
    return {s.get('id')[2:]: [(child.tag, dict(child.attrib)) for child in s] for s in root}


class IconsFollowTheirSource(unittest.TestCase):
    def test_each_icon_is_the_shells_or_lucides_own_drawing(self):
        shell = json.loads(re.search(r'const ICONS = (\{.*\});\nconst NS', SHELL_ICONS, re.S).group(1))
        compared = 0
        for name, drawn in sprite().items():
            with self.subTest(icon=name):
                if name in shell:
                    self.assertEqual(drawn, [(tag, props) for tag, props in shell[name]])
                    compared += 1
                elif LUCIDE.is_dir():       # the shell's set lacks it: the pinned Lucide file is the source
                    root = ET.fromstring(re.sub(r'<!--.*?-->', '', (LUCIDE / f'{name}.svg').read_text(encoding='utf-8'), flags=re.S))
                    self.assertEqual(drawn, [(el.tag.split('}')[-1], dict(el.attrib)) for el in root])
                    compared += 1
        self.assertGreater(compared, 5)

    def test_every_use_has_its_symbol_and_every_symbol_a_use(self):
        used = set(re.findall(r'<use href="#i-([a-z0-9-]+)"', PAGE))
        self.assertEqual(used, set(sprite()))


class PageIsAccessible(unittest.TestCase):
    def test_the_page_can_be_zoomed(self):                  # ACCESSIBILITY.md rule 4
        viewport = next(m for m in elements('meta') if m['attrs'].get('name') == 'viewport')['attrs']['content']
        self.assertNotRegex(viewport, r'user-scalable|maximum-scale|minimum-scale')
        self.assertIn('viewport-fit=cover', viewport)
        self.assertNotIn('gesturestart', page_script())     # pinch is not cancelled in script either

    def test_language_and_status(self):                     # rules 6 and 12
        self.assertIn('<html lang="en">', PAGE)
        status = next(e for e in elements('p') if e['attrs'].get('id') == 'status')
        self.assertEqual(status['attrs'].get('role'), 'status')

    def test_every_button_and_link_has_a_name(self):        # rules 1 and 2
        controls = elements('button') + elements('a')
        self.assertEqual(len(controls), 12)      # Play, Sound, Leave, Other games and the eight game buttons
        for control in controls:
            name = control['attrs'].get('aria-label') or control['text'].strip()
            self.assertTrue(name, control)

    def test_icons_are_decorative(self):
        for svg in elements('svg'):
            if svg['attrs'].get('class') != 'sprite':
                self.assertEqual(svg['attrs'].get('aria-hidden'), 'true', svg)

    def test_a_thumb_on_the_picture_or_controls_never_scrolls_or_zooms(self):
        css = page_style()
        self.assertRegex(css, r'\.screen\s*\{[^}]*touch-action:\s*none')
        self.assertRegex(css, r'\.controls,\s*\.controls \*\s*\{[^}]*touch-action:\s*none')

    def test_motion_and_contrast_are_asked_for(self):       # rule 8
        css = page_style()
        self.assertIn('@media (prefers-reduced-motion: reduce)', css)
        self.assertIn('animation: none !important', css)
        self.assertIn('@media (prefers-contrast: more)', css)

    def test_nothing_is_fetched_from_anywhere(self):
        css = page_style()
        for forbidden in ('url(', '@import', '@font-face'):
            self.assertNotIn(forbidden, css)
        hrefs = [e['attrs']['href'] for e in elements('a') + elements('use') if 'href' in e['attrs']]
        self.assertTrue(all(h.startswith('#i-') or h == '/party/' for h in hrefs), hrefs)
        self.assertEqual([e for e in elements('img') + elements('link') + elements('iframe')], [])
        self.assertEqual([e for e in elements('script') if 'src' in e['attrs']], [])

    def test_every_state_has_an_icon_and_words_not_colour_alone(self):    # rule 5
        css, script = page_style(), page_script()
        states = set(re.findall(r"link\('([a-z]+)'\)", script)) | {'idle', 'problem', 'playing', 'live'}
        self.assertEqual(states, {'idle', 'wait', 'live', 'playing', 'problem'})
        for state in states:
            self.assertIn(f'body[data-link="{state}"]', css, state)
        for klass in ('i-idle', 'i-wait', 'i-live', 'i-problem'):
            self.assertIn(f'class="ic {klass}"', PAGE)


class PageKeepsItsContract(unittest.TestCase):
    IDS = {'connect', 'connect-label', 'status', 'leave', 'sound', 'start-overlay', 'home', 'details',
           'metrics', 'path-warning', 'screen', 'who', 'who-label', 'game-name'}

    def test_the_ids_the_script_and_the_live_suites_use_are_there(self):
        ids = {e['attrs']['id'] for e in Elements().found if 'id' in e['attrs']}
        self.assertEqual(self.IDS - ids, set())

    def test_the_heading_says_the_game_and_the_player(self):
        # tests/multiplayer.spec.ts and the soak driver read the seat from the h1 ("Player N")
        heading = re.search(r'<h1>(.*?)</h1>', PAGE, re.S).group(1)
        self.assertIn('id="game-name"', heading)
        self.assertIn('id="who"', heading)
        self.assertIn('id="who-label"', heading)
        self.assertIn("'Player '+n", page_script())

    def test_the_title_is_written_once_and_the_static_page_agrees_with_it(self):
        name = re.search(r"const GAME=\{id:'[a-z0-9-]+',name:'([^']+)'\}", page_script()).group(1)
        self.assertEqual(name, 'Gauntlet II')
        self.assertIn(f'<title>Avrana Party · {name}</title>', PAGE)
        self.assertIn(f'<span class="game" id="game-name">{name}</span>', PAGE)
        self.assertIn(f'<span id="connect-label">Play {name}</span>', PAGE)
        words = re.search(r'const WORDS=\{.*?\};', page_script(), re.S).group(0)
        self.assertGreaterEqual(words.count('${GAME.name}'), 3)      # what the other states say names it too

    def test_the_words_name_controls_that_are_on_the_page(self):
        script = page_script()
        label = {e['attrs']['id']: ' '.join(e['text'].split())
                 for e in elements('button') if e['attrs'].get('id') in ('sound', 'leave', 'connect')}
        self.assertEqual(label['sound'], 'Sound')
        self.assertEqual(label['leave'], 'Leave')
        self.assertTrue(label['connect'].startswith('Play'))
        self.assertIn('Tap Sound', script)
        self.assertIn('tap Leave, then Play', script)
        self.assertNotIn('Enable sound', PAGE)                       # the button is a "Sound" toggle now
        self.assertNotIn('Mute sound', PAGE)

    def test_sound_says_whether_it_is_on(self):
        sound = next(e for e in elements('button') if e['attrs'].get('id') == 'sound')
        self.assertEqual(sound['attrs'].get('aria-pressed'), 'false')       # the picture starts muted
        self.assertIn("sound.setAttribute('aria-pressed',String(!video.muted))", page_script())

    def test_the_hub_link_and_the_host_end_have_their_place(self):
        self.assertIn("container:document.querySelector('.foot')", page_script())
        self.assertIn("const foot=document.querySelector('.foot')", page_script())
        self.assertEqual(len(re.findall(r'<footer class="foot">.*?id="home".*?</footer>', PAGE, re.S)), 1)



def to_rgb(value, ground=None):
    """A token value as (r, g, b) 0..255: #rrggbb, rgb(r g b / a) over `ground`, or oklch(L% C h)."""
    value = value.strip()
    if value.startswith('#'):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    if value.startswith('rgb('):
        r, g, b, *alpha = [float(x) for x in re.split(r'[\s/,()]+', value[4:].strip(')')) if x]
        a = alpha[0] if alpha else 1.0
        return tuple(round(a * c + (1 - a) * g0) for c, g0 in zip((r, g, b), ground))
    lightness, chroma, hue = re.match(r'oklch\(([\d.]+)%\s+([\d.]+)\s+([\d.]+)\)', value).groups()
    from math import cos, sin, radians
    L, a, b = float(lightness) / 100, float(chroma) * cos(radians(float(hue))), float(chroma) * sin(radians(float(hue)))
    l_, m_, s_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, (L - 0.1055613458 * a - 0.0638541728 * b) ** 3, (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
              -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
              -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)
    gamma = lambda c: 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return tuple(round(255 * min(1, max(0, gamma(c)))) for c in linear)


def contrast(fg, bg):
    def luminance(rgb):
        lin = [c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ContrastHolds(unittest.TestCase):
    """The pairs the page draws, at the values it declares, in the normal and the more-contrast palette
    (ACCESSIBILITY.md rule 9: 4.5:1 for text, 3:1 for control edges, icons and the focus ring)."""
    PAIRS = [
        ('text on the page', 'base-content', 'base-100', 4.5),
        ('text on the bar', 'base-content', 'material-solid', 4.5),
        ('text on a control well and a notice', 'base-content', 'base-200', 4.5),
        ('quiet text (idle status, hint) on the page', 'muted', 'base-100', 4.5),
        ('quiet text on a notice', 'muted', 'base-200', 4.5),
        ('the Play and Fire buttons', 'primary-content', 'primary', 4.5),
        ('a pressed Fire', 'primary-content', 'accent', 4.5),
        ('End, in words, on the page', 'error', 'base-100', 4.5),
        ('the warning and problem icons', 'warning', 'base-100', 3.0),
        ('the connected icon', 'success', 'base-100', 3.0),
        ('the connected mark in the bar', 'success', 'material-solid', 3.0),
        ('the focus ring', 'accent', 'base-100', 3.0),
        ('the focus ring on the bar', 'accent', 'material-solid', 3.0),
        ('the edge of a control on the page', 'control', 'base-100', 3.0),
        ('the edge of a control on the bar', 'control', 'material-solid', 3.0),
    ]

    def check(self, palette):
        ground = to_rgb(palette['--color-base-100'])
        resolve = lambda name: to_rgb(palette[f'--color-{name}'], ground)
        for what, fg, bg, minimum in self.PAIRS:
            with self.subTest(what):
                self.assertGreaterEqual(contrast(resolve(fg), resolve(bg)), minimum, f'{fg} on {bg}')

    def test_normal(self):
        self.check(tokens(page_style())[0])

    def test_more_contrast(self):
        base, more = tokens(page_style())
        self.check({**base, **more})


if __name__ == '__main__':
    unittest.main()
