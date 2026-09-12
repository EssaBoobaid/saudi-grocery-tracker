"""Three-store Dairy & Eggs matching with ranked evidence, QA and price history.

Product identity is independent of price. Matching rules, read-only quality
audits, and Gold output generation are maintained together in this module.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
import math
import re
import unicodedata
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
SILVER_DIR = BASE_DIR / "data" / "silver"
GOLD_DIR = BASE_DIR / "data" / "gold"
STORES = ["bindawood", "panda", "tamimi"]

# Matching rules

def normalize_text(value):
    text = unicodedata.normalize('NFKC', str(value or '')).lower()
    text = text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩أإآى', '0123456789اااي'))
    text = re.sub('[\u064b-\u065fـ]', '', text)
    return text.replace('×', 'x').replace('–', '-').replace('ة', 'ه')


BRAND_ALIASES = {
    'alsafidanone': 'alsafi', 'الصافي': 'alsafi', 'المراعي': 'almarai',
    'نادك': 'nadec', 'ندي': 'nada', 'السعوديه': 'saudia', 'بوك': 'puck',
    'كيري': 'kiri', 'كرافت': 'kraft', 'بريزيدنت': 'president',
    'صحه': 'saha', 'لورباك': 'lurpak', 'بلدي': 'baladi',
    'baladefarms': 'balade', 'thethreecows': 'threecows',
}


def normalize_brand(value):
    key = re.sub(r'[^a-z0-9\u0621-\u064a]', '', normalize_text(value))
    return BRAND_ALIASES.get(key, key) or 'unbranded'


# Ordered specific families before ingredients (e.g. cream cheese before cream).
FAMILIES = [
    ('eggs', r'\beggs?\b|\bبيض(?:ه)?\b'),
    ('kefir', r'kefir|كفير'),
    ('labneh', r'\blabn[ae]h\b|لبنه'),
    ('cheese', r'cheese|chesse|cheddar|mozzarella|halloumi|\bfett?a\b|gouda|جبن|شيدر|موزاريلا|حلوم'),
    ('butter', r'\bbutter\b|زبده'),
    ('ghee', r'\bghee\b|سمن'),
    ('yogurt', r'yog[uh]?urt|yoghurt|greek dessert|زبادي|روب'),
    ('laban', r'\blaban\b|\bayran\b|kefir|لبن(?!ه)|كفير'),
    ('dessert', r'pudding|custard|dessert|(?:cream|creme) caramel|مهلبيه|كاسترد|كريم كراميل'),
    ('milk', r'\bmilk\b|milkshake|\bshake\b|حليب'),
    ('cream', r'\bcream\b|قشط|كريم'),
]
ATTR_PATTERNS = {
    'fat': [('skimmed', r'skim|fat[ -]*free|zero fat|0\s*%\s*fat|خالي.*الدسم|منزوع.*الدسم'),
            ('low_fat', r'low[ -]*fat|less fat|reduced fat|\blight\b|\blite\b|قليل.*الدسم'),
            ('full_fat', r'full[ -]*(?:fat|cream)|كامل.*الدسم')],
    'processing': [('uht', r'\buht\b|long[ -]*life|طويل.*الاجل'), ('fresh', r'\bfresh\b|طازج')],
    'salt': [('unsalted', r'unsalted|no salt|غير مملح|بدون ملح'),
             ('less_salt', r'(?:less|low|reduced|light)[ -]*salt|قليل.*ملح|خفيف.*ملح'),
             ('salted', r'\bsalted\b|مملح')],
    'egg_size': [('jumbo', r'jumbo|جامبو'), ('extra_large', r'extra[ -]*large|\bxl\b|كبير جدا'),
                 ('large', r'\blarge\b|كبير'), ('medium', r'\bmedium\b|وسط|متوسط'), ('small', r'\bsmall\b|صغير')],
    'color': [('brown', r'\bbrown\b|بني'), ('white', r'\bwhite\b|ابيض|بيضاء')],
    'form': [('shredded', r'shred|grated|مبشور'), ('slices', r'slice|sliced|شرائح'),
             ('triangles', r'triangle|مثلث'), ('squares', r'squares?|مربع'),
             ('block', r'blocks?|قالب'), ('spread', r'spread|قابل.*دهن')],
    'cheese_type': [(v, pat) for v, pat in [
        ('cheddar', r'cheddar|شيدر'), ('mozzarella', r'mozzarella|موزاريلا'),
        ('feta', r'\bfett?a\b|فيتا'), ('gouda', r'gouda|جودا'),
        ('halloumi', r'halloumi|حلوم'), ('parmesan', r'parmesan|parmig|بارميزان'),
        ('edam', r'\bedam\b'), ('emmental', r'emmental'), ('cottage', r'cottage'),
        ('kashkaval', r'kashkaval|قشقوان'), ('cream', r'\bcream\b|كريمي')]],
    'cream_use': [('cooking', r'cooking|طبخ'), ('whipping', r'whipp|خفق'), ('breakfast', r'breakfast|فطور')],
    'milk_source': [('camel', r'\bcamel\b|\b(?:ال)?ابل\b|\bنوق\b'), ('goat', r'goat|ماعز'), ('plant', r'plant|oat|almond|soy|نباتي')],
    'texture': [('powder', r'powder|مجفف|بودره'), ('condensed', r'condensed|مكثف'), ('evaporated', r'evaporated|مبخر')],
}
FLAVORS = {
    'strawberry': r'strawber|strawbery|\bstraw\b|فراول', 'chocolate': r'choc|شوكولا|شوكولاته',
    'vanilla': r'vanilla|فاني', 'banana': r'banana|موز(?!اريلا)',
    'mango': r'mango|مانجو', 'blueberry': r'blueber|توت ازرق',
    'raspberry': r'rasp|توت العليق', 'blackberry': r'blackber',
    'mixed_berry': r'mixed berr|mixedberr|توت مشكل', 'peach': r'peach|خوخ',
    'pineapple': r'pineapple|اناناس', 'coffee': r'coffee|espresso|قهوه',
    'dates': r'\bdates?\b|تمر|تمري', 'caramel': r'caramel|كراميل', 'honey': r'honey|عسل',
    'garlic': r'garlic|grlic|ثوم', 'herbs': r'herbs|اعشاب', 'chili': r'chili|chilli|حار',
    'olive': r'olive|زيتون', 'mint': r'\bmint\b|نعناع', 'lemon': r'lemon|ليمون',
    'biscuit': r'biscuit|cookie|بسكويت', 'pistachio': r'pistachio|فستق',
    'cherry': r'cherry|كرز', 'hazelnut': r'hazelnut|بندق',
    'passion_fruit': r'passion\s*fruit', 'coconut': r'coconut|جوز الهند',
    'red_fruits': r'red fruits?|فواكه حمراء', 'cucumber': r'cucumber|خيار',
    'parsley': r'parsley|بقدونس', 'orange': r'orange|برتقال',
}
FEATURES = {
    'omega3': r'omega[ -]*3\b|اومي[غج]ا[ -]*3\b',
    'organic': r'organic|عضوي', 'lactose_free': r'lactose[ -]*free|خالي.*لاكتوز',
    'protein': r'protein|بروتين', 'greek': r'greek|يوناني',
    'enriched': r'enriched|fortified|مدعم|غني',
    'spreadable': r'spread|قابل.*دهن',
    'barista': r'barista|باريستا',
    'analogue': r'analogue|imitation|بديل|شبيه',
}


def attributes(product):
    text = normalize_text(f"{product.get('name_en') or ''} {product.get('name_ar') or ''}")
    family = next((v for v, pat in FAMILIES if re.search(pat, text)), None)
    result = {'brand': normalize_brand(product.get('brand')), 'family': family}
    for key, patterns in ATTR_PATTERNS.items():
        if key in ('egg_size', 'color') and family != 'eggs':
            continue
        if key in ('cheese_type', 'form') and family != 'cheese':
            continue
        if key == 'cream_use' and family != 'cream':
            continue
        # Ordered negations prevent "unsalted" being read as "salted".
        result[key] = next((v for v, pat in patterns if re.search(pat, text)), None)
    for key, pat in FEATURES.items():
        result[key] = True if re.search(pat, text) else None
    if re.search(r'conventional|non[ -]*organic|غير عضوي', text):
        result['organic'] = False
    if re.search(r'with lactose|contains lactose|يحتوي.*لاكتوز', text):
        result['lactose_free'] = False
    flavors = frozenset(v for v, pat in FLAVORS.items() if re.search(pat, text))
    result['flavor'] = flavors or ('plain' if re.search(r'\bplain\b|ساده', text) else None)
    result['flavored'] = True if flavors or re.search(r'flavou?red|نكهه', text) else None
    return result


UNITS = {
    'g': ('g', 1), 'gm': ('g', 1), 'gram': ('g', 1), 'grams': ('g', 1), 'جرام': ('g', 1), 'غ': ('g', 1),
    'kg': ('g', 1000), 'كيلو جرام': ('g', 1000), 'كجم': ('g', 1000),
    'ml': ('ml', 1), 'مل': ('ml', 1), 'l': ('ml', 1000), 'liter': ('ml', 1000),
    'litre': ('ml', 1000), 'litres': ('ml', 1000), 'liters': ('ml', 1000), 'لتر': ('ml', 1000),
    'pcs': ('pcs', 1), 'count': ('pcs', 1), 'slices': ('pcs', 1), 'triangles': ('pcs', 1),
}
UNIT_RE = r'(?:كيلو جرام|liters?|litres?|grams?|جرام|كجم|لتر|مل|kg|gm|ml|g|l)(?![a-z\u0621-\u064a])'
MEASURE_RE = r'(\d+(?:\.\d+)?)\s*(' + UNIT_RE + ')'
MULTI_RE = r'(\d+)(?:\s*\+\s*(\d+)\s*(?:free)?)?\s*[x*]\s*' + MEASURE_RE


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def close(a, b, tolerance=0.02):
    return abs(a-b) / max(a, b) <= tolerance


@dataclass(frozen=True)
class Package:
    unit: str | None
    total: float | None
    pack: float | None
    each: float | None
    count: float | None
    issues: tuple = ()
    explicit_pack: bool = False


def package(product):
    text = normalize_text(product.get('name_en') or product.get('name_ar'))
    unit, factor = UNITS.get(normalize_text(product.get('size_unit')), (None, 1))
    total = positive(product.get('total_size_value'))
    each = positive(product.get('unit_size_value'))
    pack = positive(product.get('pack_qty'))
    total = total * factor if total else (each * factor * (pack or 1) if each else None)
    each = each * factor if each else None
    issues = []
    multi = re.search(MULTI_RE, text)
    measures = list(re.finditer(MEASURE_RE, text))
    if multi:
        q, bonus, value, raw_unit = multi.groups()
        name_unit, multiplier = UNITS.get(raw_unit, (None, 1))
        name_pack = int(q) + int(bonus or 0)
        name_each = float(value) * multiplier
        if total and (unit != name_unit or not close(total, name_pack * name_each)):
            issues.append('silver_name_package_disagreement')
        unit, pack, each, total = name_unit, name_pack, name_each, name_pack * name_each
    elif measures:
        # The final physical measure is packaging; earlier grams can be protein.
        measure = measures[-1]
        name_unit, multiplier = UNITS.get(measure[2], (None, 1))
        name_each = float(measure[1]) * multiplier
        if unit == 'pcs':
            # Silver sometimes multiplies cheese portion count by itself.
            pack = 1
        if total and (unit != name_unit or not close(total, name_each * (pack or 1))):
            issues.append('silver_name_package_disagreement')
        unit, each, total = name_unit, name_each, name_each * (pack or 1)
    count_matches = list(re.finditer(r'(\d+)\s*(?:eggs?|count|pcs|portions?|slices?|triangles?|بيضه|بيض|قطع|شرائح|مثلث)(?![a-z])', text))
    count = float(count_matches[-1][1]) if count_matches else None
    if count is None and re.search(r'cheese|جبن', text):
        m = re.search(r'\b(\d+)s\b', text)
        count = float(m[1]) if m else None
    if count and (unit == 'pcs' or attributes(product)['family'] == 'eggs'):
        if total and not close(total, count):
            issues.append('silver_name_count_disagreement')
        unit, total, each, pack = 'pcs', count, count, 1
    if unit == 'pcs' and count is None:
        count = total
    return Package(unit, total, pack, each, count, tuple(issues), bool(multi))


def package_conflicts(a, b):
    reasons = []
    if a.unit and b.unit and a.unit != b.unit:
        reasons.append('size_unit')
    if a.total and b.total and a.unit == b.unit and not close(a.total, b.total):
        reasons.append('total_size')
    if a.count and b.count and a.count != b.count:
        reasons.append('explicit_count')
    if a.pack and b.pack and a.pack != b.pack:
        # A total-only representation can describe the same multipack.
        aggregate = ((a.pack == 1 and not a.explicit_pack) or (b.pack == 1 and not b.explicit_pack)) and a.total and b.total and a.unit == b.unit and close(a.total, b.total)
        if not aggregate:
            reasons.append('pack_qty')
    return reasons


def semantic_conflicts(a, b):
    return [key for key in sorted(a.keys() & b.keys())
            if a[key] is not None and b[key] is not None and a[key] != b[key]
            and not (key == 'brand' and 'unbranded' in (a[key], b[key]))]


def barcode_codes(product):
    codes = set()
    for raw in product.get('barcodes') or []:
        code = re.sub(r'[\s-]', '', str(raw))
        if code.isascii() and code.isdigit() and len(code) in (8, 12, 13, 14):
            codes.add(code)
    return codes


def valid_gtin(code):
    return len(code) in (8, 12, 13, 14) and code.isdigit() and len(set(code)) > 1 and (
        sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(code[:-1]))) + int(code[-1])
    ) % 10 == 0


def barcode_evidence(a, b):
    ca, cb = barcode_codes(a), barcode_codes(b)
    if any(valid_gtin(c) for c in ca & cb):
        return 4, 'exact_barcode'
    va = {c.zfill(14) for c in ca if valid_gtin(c)}
    vb = {c.zfill(14) for c in cb if valid_gtin(c)}
    if va & vb:
        return 3, 'normalized_barcode'
    # Equal invalid codes are supporting evidence, never exact-valid identity.
    if ca & cb:
        return 2, 'barcode_body_multifactor'
    for x in ca:
        for y in cb:
            # Only same-length EAN-13 differing in checksum, with one valid side.
            # No arbitrary prefix matching, truncation or unequal-length bodies.
            if len(x) == len(y) == 13 and x[:-1] == y[:-1] and (valid_gtin(x) or valid_gtin(y)):
                return 2, 'barcode_body_multifactor'
    return 0, None


STOP = set('the and with for from fresh pure premium quality original natural classic pack packet box tray bottle plastic special offer price full fat low milk eggs egg cheese yogurt yoghurt laban cream g ml kg pcs count'.split())
TOKEN_ALIASES = {'yoghurt': 'yogurt', 'fetta': 'feta', 'sliced': 'slices', 'slice': 'slices', 'strawbery': 'strawberry', 'spreadable': 'spread', 'aljarra': 'jar', 'jarra': 'jar', 'dates': 'date'}


def name_tokens(product):
    text = normalize_text(product.get('name_en') or product.get('name_ar'))
    text = re.sub(MULTI_RE, ' ', text)
    text = re.sub(MEASURE_RE, ' ', text)
    brand_words = set(re.findall(r'[a-z\u0621-\u064a]+', normalize_text(product.get('brand'))))
    return {TOKEN_ALIASES.get(w, w) for w in re.findall(r'[a-z\u0621-\u064a]{2,}', text) if w not in STOP | brand_words}


@dataclass
class Profile:
    product: dict
    attrs: dict
    package: Package
    tokens: set

    @property
    def uid(self):
        return self.product['store'], str(self.product['id'])


def profile(product):
    return Profile(product, attributes(product), package(product), name_tokens(product))


def pair_evidence(a, b):
    conflicts = semantic_conflicts(a.attrs, b.attrs) + package_conflicts(a.package, b.package)
    if conflicts:
        return None
    level, tier = barcode_evidence(a.product, b.product)
    known_package = a.package.unit is not None and a.package.unit == b.package.unit and a.package.total and b.package.total
    common = a.tokens & b.tokens
    similarity = 2 * len(common) / (len(a.tokens) + len(b.tokens)) if a.tokens or b.tokens else 0
    shared = sum(a.attrs.get(k) is not None and a.attrs.get(k) == b.attrs.get(k)
                 for k in a.attrs if k not in ('brand', 'family', 'enriched', 'flavored'))
    same_brand_family = a.attrs['brand'] != 'unbranded' and a.attrs['brand'] == b.attrs['brand'] and a.attrs['family'] and a.attrs['family'] == b.attrs['family']
    if not known_package:
        return None
    if level >= 3:
        return {'level': level, 'tier': tier, 'score': round(100 * level + shared + similarity, 5), 'confidence': 1.0 if level == 4 else .98}
    if not same_brand_family:
        return None
    if level == 2 and (shared >= 1 or similarity >= .65):
        return {'level': 2, 'tier': tier, 'score': round(200 + shared + similarity, 5), 'confidence': .96}
    # Missing is not conflict, but cannot positively establish a variant on names
    # alone. This prevents a generic SKU consuming a specialty SKU.
    defining = set(FEATURES) | {'flavor', 'fat', 'processing', 'cheese_type', 'form', 'egg_size', 'color', 'texture', 'milk_source', 'cream_use', 'salt'}
    if any(a.attrs.get(k) != b.attrs.get(k) for k in defining):
        return None
    if similarity < .80 or not common or shared < 1:
        return None
    return {'level': 1, 'tier': 'dairy_brand_token', 'score': round(100 + shared + similarity, 5), 'confidence': round(.90 + .02 * similarity, 3)}


def trio_evidence(ps, edges):
    pairs = list(combinations(ps, 2))
    if any(semantic_conflicts(a.attrs, b.attrs) or package_conflicts(a.package, b.package) for a, b in pairs):
        return None
    evidence = [edges.get((a.uid, b.uid)) for a, b in pairs]
    strong = sorted((e for e in evidence if e and e['level'] >= 2), key=lambda e: -e['score'])
    if len(strong) >= 2:
        # A connected barcode graph can bridge an omitted name attribute or
        # alternate barcode representation. All three pairwise guards still run.
        if len({p.attrs['brand'] for p in ps}) != 1 or len({p.attrs['family'] for p in ps}) != 1:
            return None
        relevant = strong[:2]
        confidence = min(e['confidence'] for e in relevant)
        if not all(evidence):
            confidence = min(confidence, .95)
    elif all(evidence):
        relevant = evidence
        confidence = min(e['confidence'] for e in evidence)
    else:
        return None
    weakest = min(relevant, key=lambda e: e['score'])
    available = [e for e in evidence if e]
    score = weakest['level'] * 1000 + sum(e['level'] for e in available) * 100 + sum(e['score'] % 100 for e in available)
    return {'tier': weakest['tier'], 'confidence': confidence, 'score': score}


def match_products(products):
    """Rank every plausible trio globally; refuse ambiguous or reused products.

    Each product must prefer the same whole trio. No first-valid selection or
    fallback after a stronger candidate has consumed one of its members.
    """
    profiles = [profile(p) for p in products]
    lookup = {p.uid: p for p in profiles}
    if len(lookup) != len(profiles):
        raise ValueError('Duplicate Silver store/product IDs')
    by_store = {s: sorted((p for p in profiles if p.uid[0] == s), key=lambda p: p.uid) for s in ('bindawood', 'panda', 'tamimi')}
    edges, neighbors = {}, {}
    for sa, sb in combinations(by_store, 2):
        for a in by_store[sa]:
            for b in by_store[sb]:
                if a.attrs['brand'] != b.attrs['brand'] and 'unbranded' not in (a.attrs['brand'], b.attrs['brand']):
                    continue
                evidence = pair_evidence(a, b)
                if evidence:
                    edges[a.uid, b.uid] = edges[b.uid, a.uid] = evidence
                    neighbors.setdefault(a.uid, set()).add(b.uid)
                    neighbors.setdefault(b.uid, set()).add(a.uid)
    candidates, choices = {}, {}
    for anchor in by_store['bindawood']:
        pool = set(neighbors.get(anchor.uid, set()))
        for uid in list(pool):
            pool.update(neighbors.get(uid, set()))
        for pan in sorted(uid for uid in pool if uid[0] == 'panda'):
            for tam in sorted(uid for uid in pool if uid[0] == 'tamimi'):
                ids = (anchor.uid, pan, tam)
                ps = [lookup[uid] for uid in ids]
                evidence = trio_evidence(ps, edges)
                if evidence:
                    candidates[ids] = evidence
                    for uid in ids:
                        choices.setdefault(uid, []).append(ids)
    winners, ambiguity = {}, []
    for uid, options in choices.items():
        options.sort(key=lambda ids: (-candidates[ids]['score'], ids))
        if len(options) > 1 and candidates[options[0]]['score'] - candidates[options[1]]['score'] < 1.0:
            ambiguity.append({'product': uid, 'candidate_trios': options[:5]})
        else:
            winners[uid] = options[0]
    clusters, used = [], set()
    for ids, evidence in sorted(candidates.items(), key=lambda item: (-item[1]['score'], item[0])):
        if any(uid in used or winners.get(uid) != ids for uid in ids):
            continue
        clusters.append({'products': [lookup[uid].product for uid in ids],
                         'tier': evidence['tier'], 'confidence': evidence['confidence']})
        used.update(ids)
    clusters.sort(key=lambda c: str(c['products'][0]['id']))
    return clusters, {'ambiguous_candidates': ambiguity, 'candidate_pairs': len(edges)//2,
                      'candidate_trios': len(candidates)}


# Read-only quality audits

def cluster_ids(cluster):
    return {s: str(v['raw_product_id']) for s, v in cluster['stores_data'].items()}


def audit_clusters(products, clusters):
    lookup = {(p['store'], str(p['id'])): profile(p) for p in products}
    usages, findings = Counter(), []
    semantic_count = package_count = 0
    for c in clusters:
        ids = cluster_ids(c)
        ps = [lookup[s, uid] for s, uid in ids.items() if (s, uid) in lookup]
        usages.update((s, uid) for s, uid in ids.items())
        flags = [{'kind': 'missing_silver_product', 'store': s, 'id': uid}
                 for s, uid in ids.items() if (s, uid) not in lookup]
        for a, b in combinations(ps, 2):
            semantic = semantic_conflicts(a.attrs, b.attrs)
            packaging = package_conflicts(a.package, b.package)
            semantic_count += bool(semantic)
            package_count += bool(packaging)
            if semantic:
                flags.append({'kind': 'semantic_conflict', 'stores': [a.uid[0], b.uid[0]], 'attributes': semantic})
            if packaging:
                flags.append({'kind': 'package_conflict', 'stores': [a.uid[0], b.uid[0]], 'attributes': packaging})
            if not barcode_evidence(a.product, b.product)[0] and a.product.get('barcodes') and b.product.get('barcodes'):
                flags.append({'kind': 'barcode_disagreement', 'stores': [a.uid[0], b.uid[0]]})
        undiscounted = [p.product['price'] for p in ps if p.product.get('price') and p.product['price'] > 0
                       and not p.product.get('discount_amount')
                       and not (p.product.get('original_price') and p.product['original_price'] > p.product['price'])]
        if len(undiscounted) >= 2 and max(undiscounted)/min(undiscounted) > 1.85:
            flags.append({'kind': 'price_spread_review', 'ratio': round(max(undiscounted)/min(undiscounted), 2)})
        for p in ps:
            if p.package.issues:
                flags.append({'kind': 'silver_package_corrected_from_name', 'store': p.uid[0], 'details': p.package.issues})
        if flags:
            findings.append({'canonical_name': c['product_name_en'], 'ids': ids, 'flags': flags})
    return {'semantic_conflicts': semantic_count, 'package_conflicts': package_count,
            'duplicate_usages': sum(n-1 for n in usages.values() if n > 1),
            'suspicious_clusters': findings}


def build_report(products, old, new, diagnostics):
    lookup = {(p['store'], str(p['id'])): p for p in products}
    old_map = {cluster_ids(c)['bindawood']: c for c in old}
    new_map = {cluster_ids(c)['bindawood']: c for c in new}
    added, removed, changed = [], [], []
    for key in sorted(old_map.keys() | new_map.keys()):
        before, after = old_map.get(key), new_map.get(key)
        if before and after and cluster_ids(before) == cluster_ids(after):
            continue
        record = {'canonical_name': (after or before)['product_name_en'], 'changes': [],
                  'old_tier': before.get('match_tier') if before else None,
                  'old_confidence': before.get('confidence_score') if before else None,
                  'old_price_history': before.get('price_history') if before else None,
                  'new_tier': after.get('match_tier') if after else None,
                  'new_confidence': after.get('confidence_score') if after else None}
        oi, ni = cluster_ids(before) if before else {}, cluster_ids(after) if after else {}
        for store in ('bindawood', 'panda', 'tamimi'):
            a, b = lookup.get((store, oi.get(store))), lookup.get((store, ni.get(store)))
            record['changes'].append({'store': store, 'old_product_id': oi.get(store), 'new_product_id': ni.get(store),
                                      'old_name': (a or {}).get('name_en') or (a or {}).get('name_ar'),
                                      'new_name': (b or {}).get('name_en') or (b or {}).get('name_ar'),
                                      'old_barcodes': (a or {}).get('barcodes'), 'new_barcodes': (b or {}).get('barcodes')})
        reasons = []
        if before:
            ps = [profile(lookup[s, uid]) for s, uid in oi.items() if (s, uid) in lookup]
            for a, b in combinations(ps, 2):
                reasons.extend(semantic_conflicts(a.attrs, b.attrs))
                reasons.extend(package_conflicts(a.package, b.package))
            if len(ps) != 3:
                record['loss_class'] = 'C_missing_silver_product'
            elif reasons:
                record['loss_class'] = 'A_explicit_conflict'
            elif not all(pair_evidence(a, b) for a, b in combinations(ps, 2)):
                record['loss_class'] = 'C_insufficient_identity_evidence'
            else:
                record['loss_class'] = 'C_ambiguous_or_stronger_competitor'
        record['reason'] = sorted(set(reasons)) or ['ranked_reciprocal_evidence' if after else record['loss_class']]
        (added if before is None else removed if after is None else changed).append(record)
    stats = lambda rows: {'clusters': len(rows), 'matched_products': 3*len(rows),
                         'coverage_percent': round(300*len(rows)/len(products), 2) if products else 0,
                         'tiers': dict(Counter(c['match_tier'] for c in rows))}
    metadata_changes = [{'canonical_name': new_map[k]['product_name_en'],
                         'fields': {f: {'old': old_map[k].get(f), 'new': new_map[k].get(f)}
                                    for f in ('size', 'unit', 'quantity', 'total_size')
                                    if old_map[k].get(f) != new_map[k].get(f)}}
                        for k in sorted(old_map.keys() & new_map.keys())]
    metadata_changes = [c for c in metadata_changes if c['fields']]
    return {'package_metadata_changes': metadata_changes, 'total_silver': len(products), 'before': stats(old), 'after': stats(new),
            'added_count': len(added), 'removed_count': len(removed), 'changed_count': len(changed),
            'unsafe_removed_count': sum(r.get('loss_class') == 'A_explicit_conflict' for r in removed),
            'removed_classification': dict(Counter(r['loss_class'] for r in removed)),
            'added': added, 'removed': removed, 'changed': changed,
            'previous_qa': audit_clusters(products, old), 'qa': audit_clusters(products, new),
            'candidate_diagnostics': diagnostics}


# Gold output and price history

def select_canonical_product(prods: list[dict[str, Any]]) -> dict[str, Any]:
    store_priority = {"bindawood": 0, "panda": 1, "tamimi": 2}
    sorted_prods = sorted(prods, key=lambda x: store_priority.get(x["store"], 99))
    return sorted_prods[0]


def load_dairy() -> list[dict[str, Any]]:
    items = []
    for store in STORES:
        path = SILVER_DIR / store / "dairy_and_eggs_clean.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                items.extend(json.load(f))
    return items


def load_existing_history(file_path: Path) -> dict[str, list[dict[str, Any]]]:
    history_map = defaultdict(list)
    if not file_path.exists():
        return history_map

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
            for item in old_data:
                key = item.get("barcode") or item.get("product_name_en")
                if key and "price_history" in item:
                    # Keep only price observations from the active store set,
                    # retaining valid BinDawood/Panda/Tamimi history.
                    history_map[str(key)] = [
                        entry
                        for entry in item["price_history"]
                        if set((entry.get("stores_prices") or {})).issubset(STORES)
                    ]
    except Exception as e:
        print(f"  [!] Note: Could not read prior history: {e}")

    return history_map


def main(comparison_baseline: Path | None = None, dry_run: bool = False):
    print("=== جاري مطابقة الألبان والبيض (3-STORES ONLY + قواعد الأمان الصارمة) ===")
    products = load_dairy()
    if not products:
        print("[!] لم يتم العثور على ملفات dairy_and_eggs_clean.json")
        return

    out_file = GOLD_DIR / "matched_dairy_and_eggs.json"
    prior_history = load_existing_history(out_file)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    old_data = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else []
    previous_by_anchor = {
        str(c["stores_data"]["bindawood"]["raw_product_id"]): c for c in old_data
    }
    clusters, diagnostics = match_products(products)

    # 5. تشكيل ملف الذهب وتوحيد المفاتيح مع جدول المشروبات
    formatted = []

    for c in clusters:
        prods = c["products"]
        canonical = select_canonical_product(prods)
        canonical_package = package(canonical)

        valid_prices = [p["price"] for p in prods if p.get("price") is not None]
        avg_price = round(sum(valid_prices) / len(valid_prices), 2) if valid_prices else None
        min_price = min(valid_prices) if valid_prices else None
        max_price = max(valid_prices) if valid_prices else None
        price_diff = round(max_price - min_price, 2) if (min_price and max_price) else 0.0

        stores_data = {}
        for p in prods:
            stores_data[p["store"]] = {
                "price": p.get("price"),
                "original_price": p.get("original_price"),
                "discount_amount": p.get("discount_amount"),
                "discount_percentage": p.get("discount_percentage"),
                "has_discount": bool(p.get("discount_amount") and p["discount_amount"] > 0),
                "image_url": p.get("image_url"),
                "raw_product_id": p.get("id"),
            }

        all_barcodes = canonical.get("barcodes") or []
        primary_barcode = all_barcodes[0] if all_barcodes else None

        # بناء وتحديث التاريخ التراكمي
        lookup_key = str(primary_barcode or canonical.get("name_en"))
        existing_history = prior_history.get(lookup_key, [])
        previous = previous_by_anchor.get(str(canonical["id"]))
        selected_ids = {s: str(v["raw_product_id"]) for s, v in stores_data.items()}
        if previous and selected_ids != {
            s: str(v["raw_product_id"]) for s, v in previous["stores_data"].items()
        }:
            # Never attach an old, differently selected SKU's observations to
            # the corrected identity. The audit records the previous selection.
            existing_history = []

        current_entry = {
            "date": today_str,
            "stores_product_ids": selected_ids,
            "avg_price": avg_price,
            "min_price": min_price,
            "max_price": max_price,
            "stores_prices": {k: v["price"] for k, v in stores_data.items()},
        }

        updated_history = [h for h in existing_history if h.get("date") != today_str]
        updated_history.append(current_entry)

        formatted.append({
            "product_name_ar": canonical.get("name_ar"),
            "product_name_en": canonical.get("name_en"),
            "brand": canonical.get("brand"),
            "category": "dairy_and_eggs",
            "size": canonical_package.each,
            "unit": canonical_package.unit,
            "quantity": canonical_package.pack,
            "total_size": canonical_package.total,
            "barcode": primary_barcode,
            "image_url": canonical.get("image_url"),
            "canonical_source": canonical.get("store"),
            "match_tier": c["tier"],
            "confidence_score": c["confidence"],
            "matched_stores_count": 3,
            "matched_stores": ["bindawood", "panda", "tamimi"],
            "price_metrics": {
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "price_diff": price_diff,
            },
            "price_history": updated_history,
            "stores_data": stores_data,
        })

    qa = audit_clusters(products, formatted)
    if qa["semantic_conflicts"] or qa["package_conflicts"] or qa["duplicate_usages"]:
        raise ValueError("Dairy QA failed; Gold was not written")
    if dry_run:
        comparison_data = json.loads(comparison_baseline.read_text(encoding="utf-8")) if comparison_baseline else old_data
        report = build_report(products, comparison_data, formatted, diagnostics)
        return report, formatted

    # حفظ الملف
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    archive_dir = GOLD_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / f"matched_dairy_and_eggs_{today_str}.json"
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    total_prods = len(products)
    matched_prods = len(formatted) * 3
    pct = round(matched_prods / total_prods * 100, 2) if total_prods else 0.0

    print("\n" + "=" * 60)
    print("📊 DAIRY & EGGS REPORT (EXCLUSIVE 3-STORE ONLY):")
    print(f"   • Total Products In Silver : {total_prods}")
    print(f"   • 3-Store Matches (Clusters): {len(formatted)} clusters")
    print(f"   • Matched Products Count   : {matched_prods}")
    print(f"   • Pure 3-Store Coverage    : {pct}%")
    print(f"   • Active File Saved        : {out_file.name}")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-baseline", type=Path, help="Compare QA against an earlier Gold snapshot")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing Gold or diagnostics")
    parser.add_argument("--audit-only", action="store_true", help="Audit existing Gold without writing files")
    parser.add_argument("--gold", type=Path, default=GOLD_DIR / "matched_dairy_and_eggs.json", help="Gold file to inspect with --audit-only")
    args = parser.parse_args()
    if args.audit_only:
        rows = json.loads(args.gold.read_text(encoding="utf-8"))
        print(json.dumps(audit_clusters(load_dairy(), rows), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    result = main(args.comparison_baseline, args.dry_run)
    if args.dry_run and result:
        print(json.dumps({k: result[0][k] for k in ("before", "after", "added_count", "removed_count", "changed_count")}, indent=2))
