/* 자재 매칭 엔진: 내역서 한 줄(품명·규격)을 단가 자료 품목과 비교해 후보를 고릅니다.
   브라우저와 Node 양쪽에서 씁니다. */
(function (root) {
  const FEAT = {
    mat: [
      ['sts316', /316/],
      ['sts', /스테인리스|스텐인리스|스텐|STS|SUS|\bSU\b|\d+SU\b/i],
      ['cpvc', /C-?PVC|CPVC/i],
      ['pvdf', /PVDF/i],
      ['pvc', /PVC|염화비닐/i],
      ['pp', /\bPP\b|폴리프로필렌/i],
      ['pe', /\bPE\b|폴리에틸렌/i],
      ['bronze', /청동/],
      ['brass', /황동/],
      ['cu', /동관|동파이프|동관이음|구리/],
      ['ci', /주철|덕타일|닥타일/],
      ['black', /흑관|흑강관|흑(?=엘보|티|레듀|캡|니플|유니온|소켓)/i],
      ['white', /백관|백강관|백(?=엘보|티|레듀|캡|니플|유니온|소켓|플러그)|아연도/i],
      ['steel', /강관|탄소강|철(?!물)|단조|A105|STL/i],
    ],
    part: [
      ['ballvalve', /볼\s*밸브|볼밸브|BALL\s*VALVE|Ball/i],
      ['butterfly', /버터플라이|버터밸브|BUTTERFLY/i],
      ['gate', /게이트|GATE|OS&Y/i],
      ['globe', /글로브|GLOBE/i],
      ['check', /체크|첵크|CHECK/i],
      ['diaphragm', /다이어프램|DIAPHRAGM/i],
      ['strainer', /스트레이너|STRAINER|여과기/i],
      ['trap', /트랩|TRAP/i],
      ['prv', /감압/],
      ['safety', /안전\s*밸브|안전밸브|RELIEF/i],
      ['flex', /후렉시블|플렉시블|플랙시블|FLEXIBLE|벨로즈|신축|주름관/i],
      ['insul', /보온|단열|발포/],
      ['gauge', /압력계|온도계|게이지/],
      ['gasket', /가스켓|가스킷|GASKET|패킹/i],
      ['blind', /막힘|맹\s*(후렌지|플랜지)|맹후렌지|BLIND/i],
      ['flange', /플랜지|후렌지|FLANGE/i],
      ['reducer', /레듀|례듀|리듀|REDUCER/i],
      ['elbow', /엘보|ELBOW|곡관/i],
      ['tee', /티이|(^|[^가-힣])티($|[^가-힣])|TEE|T관|티\(/i],
      ['cap', /캡|CAP/i],
      ['nipple', /닛블|니플|NIPPLE/i],
      ['union', /유니온|UNION/i],
      ['socket', /소켓|SOCKET|커플링/i],
      ['plug', /플러그|PLUG/i],
      ['valve', /밸브|VALVE/i],
      ['pipe', /관|파이프|PIPE|튜브/i],
    ],
    join: [
      ['weld', /용접|맞대기/], ['thread', /나사/], ['press', /프레스/], ['groove', /그루브|홈\(/],
    ],
  };
  const SCH = [['s10', /10S\b|S\/?10\b|SCH\s*10|Sch10/i], ['s20', /20S\b|SCH\s*20/i], ['s40', /SCH\s*\/?\s*40|S\/40|Sch40/i], ['s80', /SCH\s*80|Sch80/i]];

  function feats(text) {
    const f = { mat: null, part: null, join: null, sch: null };
    for (const k of ['mat', 'part', 'join']) for (const [id, re] of FEAT[k]) if (re.test(text)) { f[k] = id; break; }
    for (const [id, re] of SCH) if (re.test(text)) { f.sch = id; break; }
    f.deg45 = /45\s*(°|˚|도|D\b|\(|엘보)|엘보\s*45|45\s*Elbow/i.test(text);
    f.deg90 = /90\s*(°|˚|도|D\b|엘보)|90\s*ELBOW/i.test(text);
    f.seamless = /SEAMLESS|무계목/i.test(text);
    return f;
  }

  // 규격에서 호칭 크기를 뽑습니다. 외경·두께·중량 같은 숫자는 버립니다.
  function sizes(spec) {
    let s = String(spec || '').replace(/(외경|두께|단중|중량|길이)\s*:?\s*[\d.]+\s*(㎜|mm|㎏\/m|kg\/m|㎏)?/gi, ' ')
      .replace(/\d+(\.\d+)?\s*T\s*x\s*/gi, ' ')         // 보온 두께 25Tx
      .replace(/\d+\s*(K|㎏|kg)\b\s*[*,]?/gi, ' ')       // 압력 등급 10K, 10kg
      .replace(/[½¾¼]inch|\d+\/\d+["']?|inch/gi, ' ');
    const su = /SU\b/i.test(s);
    let m = s.match(/(?:D|OD|호칭(?:경)?:?)?\s*(\d{1,4})\s*(?:A|㎜|mm|SU)?\s*[×xX*]\s*(?:D|OD)?\s*(\d{1,4})/);
    if (m) return { d: [+m[1], +m[2]], su };
    m = s.match(/(?:\bD|OD|호칭(?:경)?\s*:?)\s*(\d{1,4})/i) || s.match(/(\d{1,4})\s*(?:A\b|㎜|mm|SU\b)/i) || s.match(/^\s*(\d{1,4})\s*$/);
    return m ? { d: [+m[1]], su } : { d: [], su };
  }

  function sameSize(a, b) {
    if (!a.d.length || !b.d.length) return false;
    if (a.d[0] !== b.d[0]) return false;
    const a2 = a.d[1] ?? a.d[0], b2 = b.d[1] ?? b.d[0];
    return a2 === b2;
  }

  // 단가 자료 한 품목을 매칭용으로 준비합니다.
  function prepare(item) {
    const text = [item.cat, item.name, item.form, item.spec].filter(Boolean).join(' ');
    const f = feats(text);
    const sz = sizes(item.spec || '');
    // 부속 종류가 안 적힌 이경(두 크기가 다른) 품목은 레듀서로 봅니다.
    if ((f.part === 'pipe' || !f.part) && sz.d.length === 2 && sz.d[0] !== sz.d[1] && /이음/.test(text)) f.part = 'reducer';
    return { ...item, _f: f, _s: sz, _t: text, _x: { wan: /완제품/.test(text), long: /Long|LONG/.test(text), gong: /공업용/.test(text) } };
  }

  // 부속 종류별로 묶어 두면 수천 줄도 빠르게 비교합니다.
  function index(items) {
    const by = new Map();
    for (const c of items) { const k = c._f.part || '-'; if (!by.has(k)) by.set(k, []); by.get(k).push(c); }
    return { by, all: items };
  }

  const MAT_OK = {
    sts316: ['sts316'], sts: ['sts', 'sts316'], cpvc: ['cpvc'], pvc: ['pvc', 'cpvc'], pvdf: ['pvdf'], pp: ['pp'], pe: ['pe'],
    bronze: ['bronze'], brass: ['brass', 'bronze'], cu: ['cu'], ci: ['ci'], white: ['white', 'steel'], black: ['black', 'steel'], steel: ['steel', 'white', 'black', 'ci'],
  };

  const METAL_FIT = ['flange', 'blind', 'elbow', 'tee', 'reducer', 'cap', 'nipple', 'union', 'socket', 'plug'];
  function scoreOne(q, c) {
    if (q.f.part !== c._f.part) {
      const valveish = ['ballvalve', 'butterfly', 'gate', 'globe', 'check', 'diaphragm', 'valve'];
      if (!(q.f.part === 'valve' && valveish.includes(c._f.part))) return -1;
    }
    if (!sameSize(q.s, c._s)) return -1;
    let sc = 10;
    if (q.f.mat) {
      if (!c._f.mat) return -1;
      else if (q.f.mat === c._f.mat) sc += 4;
      else if ((MAT_OK[q.f.mat] || []).includes(c._f.mat)) sc += 1;
      else return -1;
    }
    if (q.f.join && c._f.join) sc += q.f.join === c._f.join ? 2 : -6;
    if (q.f.sch && c._f.sch) sc += q.f.sch === c._f.sch ? 2 : -2;
    if (!q.f.sch && (c._f.sch === 's40' || c._f.sch === 's80')) sc -= 0.5;
    if (q.f.part === 'elbow') {
      if (q.f.deg45 && !c._f.deg45 && c._f.deg90) return -1;
      sc += q.f.deg45 === c._f.deg45 ? 1 : -4;
    }
    if (c._f.seamless && !q.f.seamless) sc -= 1;
    if (c._x.gong) sc += 0.5;
    if (c._x.wan) sc += 0.5;
    if (c._x.long) sc += 0.3;
    if (q.s.su !== c._s.su) sc -= 3;
    return sc;
  }

  // 내역서 한 줄 → 후보 목록(점수순)과 판정
  function match(line, catalog) {
    const q = { f: feats(line.name + ' ' + (line.spec || '')), s: sizes(line.spec || '') };
    if (!q.s.d.length) q.s = sizes(line.name);
    // 재질이 안 적힌 금속 부속(용접합후렌지, 엘보 등)은 철(강관용)로 봅니다.
    if (!q.f.mat && METAL_FIT.includes(q.f.part)) q.f.mat = 'steel';
    const cands = [];
    const valveish = ['ballvalve', 'butterfly', 'gate', 'globe', 'check', 'diaphragm', 'valve'];
    const pool = catalog.by ? (q.f.part === 'valve' ? valveish.flatMap(k => catalog.by.get(k) || []) : (catalog.by.get(q.f.part) || [])) : catalog;
    for (const c of pool) {
      const sc = scoreOne(q, c);
      if (sc >= 0) cands.push({ item: c, score: sc });
    }
    cands.sort((a, b) => b.score - a.score || (a.item.src === 'kpi' ? -1 : 1));
    const top = cands[0], second = cands[1];
    let status = 'none';
    if (top) status = top.score >= 13 && (!second || top.score - second.score >= 0.3 || top.item.p === second.item.p) ? 'auto' : 'check';
    return { q, status, cands: cands.slice(0, 8) };
  }

  const api = { feats, sizes, prepare, index, match };
  if (typeof module !== 'undefined') module.exports = api; else root.Matcher = api;
})(this);
