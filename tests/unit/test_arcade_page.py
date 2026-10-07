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

    def test_every_prompt_that_waits_for_a_picture_goes_when_it_plays(self):
        script = page_script()
        prompts = re.search(r"const PROMPTS=/\^\((.*?)\)/;", script).group(1).split('|')
        said = re.findall(r"status\.textContent='((?:Tap Sound|Connected, but no picture)[^']*)'", script)
        self.assertGreaterEqual(len(said), 3)      # the track failing to play, the Sound tap failing, no picture yet
        for words in said:
            self.assertTrue(any(words.startswith(p) for p in prompts), words)
        self.assertIn('if(PROMPTS.test(status.textContent))', script)

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


def split_top(text):
    """Split on the commas that are not inside parentheses (a selector list, the arguments of :not())."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(text):
        depth += (c == '(') - (c == ')')
        if c == ',' and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    return [p.strip() for p in parts + [text[start:]] if p.strip()]


def css_rules(css):
    """[(selector, {property: value}, media)] in source order: one entry per selector of a list, @media
    blocks flattened (media is its condition, '' outside one), comments and @keyframes left out."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    def block(text, media):
        out, pos = [], 0
        while True:
            head = re.compile(r'\s*([^{}]+)\{').match(text, pos)
            if not head:
                return out
            name, depth, j = head.group(1).strip(), 1, head.end()
            while depth:
                depth += (text[j] == '{') - (text[j] == '}')
                j += 1
            body, pos = text[head.end():j - 1], j
            if name.startswith('@media'):
                out += block(body, name[len('@media'):].strip())
            elif not name.startswith('@'):
                decls = {k: ' '.join(v.split()) for k, v in re.findall(r'(-{0,2}[a-zA-Z][\w-]*)\s*:\s*([^;]+)', body)}
                out += [(' '.join(sel.split()), decls, media) for sel in split_top(name)]
    return block(css, '')


def specificity(selector):
    """(ids, classes + attributes + pseudo-classes, types) as the cascade counts them; :where() counts
    nothing, :not() and :is() count their most specific argument."""
    a = b = c = 0
    rest = re.sub(r'"[^"]*"', '""', selector)
    while True:
        found = re.search(r':(not|is|where)\(', rest)
        if not found:
            break
        depth, j = 1, found.end()
        while depth:
            depth += (rest[j] == '(') - (rest[j] == ')')
            j += 1
        if found.group(1) != 'where':
            top = max(specificity(arg) for arg in split_top(rest[found.end():j - 1]))
            a, b, c = a + top[0], b + top[1], c + top[2]
        rest = rest[:found.start()] + rest[j:]
    a += len(re.findall(r'#[\w-]+', rest))
    b += len(re.findall(r'\.[\w-]+', rest)) + len(re.findall(r'\[[^\]]*\]', rest)) + len(re.findall(r'(?<!:):(?!:)[\w-]+', rest))
    c += len(re.findall(r'::[\w-]+', rest)) + len(re.findall(r'(?:^|[\s>+~])[a-zA-Z][\w-]*', rest))
    return (a, b, c)


class ContrastHolds(unittest.TestCase):
    """The pairs the page draws, at the values it declares, in the normal and the more-contrast palette
    (ACCESSIBILITY.md rule 9: 4.5:1 for text, 3:1 for control edges, icons and the focus ring): every
    control at rest, held and disabled, upright (a well on the page) and sideways (smoky, over the stage)."""
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
        # upright: a well, and a pill that is only an outline, on the page
        ('the edge of a control well', 'control', 'base-200', 3.0),
        ('a disabled control, in words', 'faint', 'base-200', 4.5),
        # held, upright and sideways: ink on the ground, the same ink as its edge
        ('a held control', 'primary-content', 'primary', 4.5),
        ('the edge of a held control', 'primary', 'base-100', 3.0),
        ('the focus ring inside Fire and a held control', 'primary-content', 'primary', 3.0),
        ('the focus ring inside a held Fire', 'primary-content', 'accent', 3.0),
        # sideways: smoky, over the page's ground or a dark picture; over a white picture the words still hold
        ('words on a control over the stage', 'base-content', 'material', 4.5),
        ('the edge of a control over the stage', 'control', 'material', 3.0),
        ('the focus ring on a control over the stage', 'accent', 'material', 3.0),
        ('words on a control over a white picture', 'base-content', 'material', 4.5, '#ffffff'),
    ]

    def check(self, palette):
        for what, fg, bg, minimum, *under in self.PAIRS:
            behind = to_rgb(under[0] if under else palette['--color-base-100'])
            resolve = lambda name: to_rgb(palette[f'--color-{name}'], behind)
            with self.subTest(what):
                self.assertGreaterEqual(contrast(resolve(fg), resolve(bg)), minimum, f'{fg} on {bg}')

    def test_normal(self):
        self.check(tokens(page_style())[0])

    def test_more_contrast(self):
        base, more = tokens(page_style())
        self.check({**base, **more})


class SpecificityIsCountedRight(unittest.TestCase):
    """The helper the cascade test below leans on, against the cases the stylesheet has."""

    def test_the_cases_the_page_has(self):
        for selector, counted in [
            ('.act:not(.fire):not(:disabled)', (0, 3, 0)), ('.dpad button.held', (0, 2, 1)),
            ('.controls button:disabled', (0, 2, 1)), ('#avrana-party-end', (1, 0, 0)),
            ('.controls :focus-visible', (0, 2, 0)), (':where(.a, .b)', (0, 0, 0)),
            ('body[data-link="wait"] .i-wait', (0, 2, 1)), ('#connect[aria-busy="true"]::after', (1, 1, 1)),
        ]:
            self.assertEqual(specificity(selector), counted, selector)


class PressablesKeepTheirLook(unittest.TestCase):
    """Upright and sideways differ in where the controls are and in what they rest on, and in nothing
    else: the same edge (the 3:1 `control` token, which more contrast raises) and the same held look.
    The contrast pairs above hold for the colours the page uses; these hold the page to using them."""
    PRESSABLE = re.compile(r'\.(?:pill|act|fire|tool)\b|\.dpad button')
    COLOURS = {'background', 'background-color', 'color', 'border', 'border-color', 'outline-color'}

    @staticmethod
    def positive(selector):
        """The selector without its :not() parts: :not(:disabled) is the resting state, not the disabled one."""
        return re.sub(r':not\([^)]*\)', '', selector)

    @classmethod
    def state(cls, selector):
        selector = cls.positive(selector)
        if ':disabled' in selector:
            return 'disabled'
        if '.held' in selector or ':active' in selector:
            return 'held'
        return 'focus' if ':focus-visible' in selector else 'resting'

    def pressables(self):
        return [(i, sel, decls, media) for i, (sel, decls, media) in enumerate(css_rules(page_style()))
                if self.PRESSABLE.search(sel)]

    def test_every_edge_is_the_control_edge_at_rest_and_ink_when_held(self):
        seen = 0
        for _, selector, decls, media in self.pressables():
            for prop in ('border', 'border-color'):
                if prop not in decls:
                    continue
                state = self.state(selector)
                allowed = {'resting': {'primary'} if '.fire' in self.positive(selector) else {'control'},
                           'held': {'primary', 'accent'}, 'disabled': {'line-strong'}}[state]
                used = set(re.findall(r'var\(--color-([a-z0-9-]+)', decls[prop]))
                self.assertTrue(used and used <= allowed, f'{selector} ({media or "upright"}): {prop} is {decls[prop]}')
                seen += 1
        self.assertGreater(seen, 8)

    def test_sideways_changes_the_fill_and_nothing_a_control_is_read_by(self):
        css = page_style()
        sideways = [(sel, decls) for sel, decls, media in css_rules(css) if 'orientation: landscape' in media]
        self.assertTrue(sideways)
        for selector, decls in sideways:
            if self.PRESSABLE.search(selector):
                self.assertEqual(self.COLOURS & set(decls), set(), f'{selector} recolours a control sideways')
        fills = [decls['--fill'] for _, decls in sideways if '--fill' in decls]
        self.assertEqual(fills, ['var(--color-material)'])

    def test_the_held_look_beats_every_resting_look(self):
        rules = self.pressables()
        held = [r for r in rules if self.state(r[1]) == 'held']
        resting = [r for r in rules if self.state(r[1]) == 'resting' and self.COLOURS & set(r[2])]
        self.assertGreaterEqual(len(held), 8)
        for h_index, h_selector, *_ in held:
            for r_index, r_selector, *_ in resting:
                h, r = specificity(h_selector), specificity(r_selector)
                self.assertTrue(h > r or (h == r and h_index > r_index),
                                f'{r_selector} {r} would beat {h_selector} {h}: a held control would not look held')

    def test_a_ring_on_the_ink_is_dark(self):
        rings = {sel: decls.get('outline-color') for sel, decls, _ in css_rules(page_style()) if ':focus-visible' in sel}
        for selector in ('.fire:focus-visible', '.controls .held:focus-visible'):
            self.assertEqual(rings.get(selector), 'var(--color-primary-content)', selector)


if __name__ == '__main__':
    unittest.main()
