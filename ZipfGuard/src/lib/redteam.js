/**
 * Reproducible, entirely synthetic password-policy laboratory.
 * No network, storage, real credential collection, or authentication endpoints.
 * The AI baseline is a fitted character trigram model, not a neural network.
 */

export const ROOT_WORDS = [
  'cedar', 'maple', 'cloud', 'river', 'panda', 'tiger', 'cobalt', 'amber',
  'coral', 'lunar', 'forest', 'meadow', 'delta', 'comet', 'spruce', 'willow',
  'harbor', 'lotus', 'otter', 'falcon', 'orchid', 'silk', 'pebble', 'bamboo',
];
export const PHRASE_WORDS = [
  'birch', 'ocean', 'quartz', 'mango', 'violet', 'dune', 'raven', 'mint',
  'opal', 'brook', 'linen', 'plum', 'snow', 'fern', 'cove', 'reed',
];
export const SYNTHETIC_SUFFIXES = ['123', '2026', '01', '88', '!', '7', '99', '520', '', '42', '2025', '@'];
const EOS = '\u0003';
const UNK = '\u0000';
const START = '\u0002';

export function seededRandom(seed = 42) {
  let state = Number(seed) >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Public grammar. This is enumerated before any samples are drawn. */
export function originalCandidateSpace() {
  const values = [];
  for (const root of ROOT_WORDS) {
    for (const suffix of SYNTHETIC_SUFFIXES) {
      values.push(root + suffix);
      values.push(root[0].toUpperCase() + root.slice(1) + suffix);
    }
  }
  return [...new Set(values)];
}

export function phraseCandidateSpace() {
  const values = [];
  for (const a of PHRASE_WORDS) for (const b of PHRASE_WORDS) for (const c of PHRASE_WORDS) {
    values.push(`${a}-${b}-${c}`);
  }
  return values;
}

function cdfSampler(weights, random) {
  const total = weights.reduce((a, b) => a + b, 0);
  const cdf = [];
  weights.reduce((sum, weight) => { cdf.push(sum + weight / total); return sum + weight / total; }, 0);
  return () => {
    const x = random();
    let lo = 0;
    let hi = cdf.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (cdf[mid] < x) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  };
}

/** Independent samples from a known synthetic truncated rank distribution. */
export function createSyntheticDataset({ size = 9000, seed = 42, exponent = 1.08, drift = 0 } = {}) {
  const count = Math.max(100, Math.min(100000, Math.round(Number(size) || 9000)));
  const candidates = originalCandidateSpace();
  const random = seededRandom(seed);
  const weights = candidates.map((_, index) => Math.pow(index + 1, -exponent));
  const sample = cdfSampler(weights, random);
  const shift = Math.round(Math.max(0, Math.min(1, drift)) * 70);
  const samples = Array.from({ length: count }, (_, id) => ({
    id,
    password: candidates[(sample() + shift) % candidates.length],
  }));
  const trainEnd = Math.floor(count * 0.6);
  const validationEnd = Math.floor(count * 0.8);
  return {
    samples,
    train: samples.slice(0, trainEnd),
    validation: samples.slice(trainEnd, validationEnd),
    test: samples.slice(validationEnd),
    candidates,
    metadata: {
      synthetic: true, seed, exponent, drift,
      split: 'Independent synthetic users: 60% train / 20% validation / 20% test',
      candidateSource: 'Public fixed grammar; no test strings used for candidate construction',
    },
  };
}

function toPassword(item) { return typeof item === 'string' ? item : item.password; }

export function frequencyCounts(samples) {
  const counts = new Map();
  for (const item of samples) {
    const password = toPassword(item);
    counts.set(password, (counts.get(password) || 0) + 1);
  }
  return counts;
}

/** Character model with recursive interpolation and an explicit unknown symbol. */
export function trainNgram(samples, { order = 3, smoothing = 0.3 } = {}) {
  if (!Number.isInteger(order) || order < 1 || order > 5) throw new Error('order must be an integer in [1, 5]');
  if (!(smoothing > 0)) throw new Error('smoothing must be positive');
  const alphabet = new Set([EOS, UNK]);
  for (const item of samples) for (const character of toPassword(item)) alphabet.add(character);
  const tables = Array.from({ length: order }, () => new Map());
  const totals = Array.from({ length: order }, () => new Map());
  let tokens = 0;
  for (const item of samples) {
    const characters = [...toPassword(item), EOS];
    let history = START.repeat(order - 1);
    for (const character of characters) {
      tokens += 1;
      for (let depth = 0; depth < order; depth += 1) {
        const context = depth ? history.slice(-depth) : '';
        if (!tables[depth].has(context)) tables[depth].set(context, new Map());
        const local = tables[depth].get(context);
        local.set(character, (local.get(character) || 0) + 1);
        totals[depth].set(context, (totals[depth].get(context) || 0) + 1);
      }
      history += character;
    }
  }
  return { type: 'character-ngram', order, smoothing, alphabet, tables, totals, samples: samples.length, tokens };
}

export function ngramProbability(model, character, history) {
  const symbol = model.alphabet.has(character) ? character : UNK;
  const vocabularySize = model.alphabet.size;
  const baseCounts = model.tables[0].get('');
  let probability = ((baseCounts?.get(symbol) || 0) + model.smoothing)
    / ((model.totals[0].get('') || 0) + model.smoothing * vocabularySize);
  for (let depth = 1; depth < model.order; depth += 1) {
    const context = history.slice(-depth);
    const total = model.totals[depth].get(context) || 0;
    if (!total) continue;
    const count = model.tables[depth].get(context)?.get(symbol) || 0;
    const priorStrength = model.smoothing * vocabularySize;
    probability = (count + priorStrength * probability) / (total + priorStrength);
  }
  return probability;
}

/** Surprisal is model NLL, not an absolute estimate of attacker guess number. */
export function scoreNgram(model, password) {
  let history = START.repeat(model.order - 1);
  let surprisalBits = 0;
  let unknownCharacters = 0;
  for (const character of [...password, EOS]) {
    if (!model.alphabet.has(character)) unknownCharacters += 1;
    surprisalBits -= Math.log2(ngramProbability(model, character, history));
    history += model.alphabet.has(character) ? character : UNK;
  }
  return {
    surprisalBits,
    bitsPerCharacter: surprisalBits / Math.max(1, [...password].length + 1),
    unknownCharacters,
    interpretation: 'Character-model surprisal; not password entropy or real-world guess cost',
  };
}

/** Attack rankings use training information and a public candidate universe only. */
export function rankCandidates(train, candidates, { attack = 'hybrid', order = 3, empiricalWeight = 0.65 } = {}) {
  const model = trainNgram(train, { order });
  const counts = frequencyCounts(train);
  const unique = [...new Set(candidates)];
  const scores = unique.map(password => ({ password, nll: scoreNgram(model, password).surprisalBits, count: counts.get(password) || 0 }));
  const minNll = scores.length ? Math.min(...scores.map(item => item.nll)) : 0;
  const normalization = scores.reduce((sum, item) => sum + Math.pow(2, -(item.nll - minNll)), 0) || 1;
  const inUniverseCount = scores.reduce((sum, item) => sum + item.count, 0);
  for (const item of scores) {
    const neuralBaseline = Math.pow(2, -(item.nll - minNll)) / normalization;
    const empirical = item.count / Math.max(1, inUniverseCount);
    item.probability = attack === 'frequency' ? empirical
      : attack === 'ngram' ? neuralBaseline
        : empiricalWeight * empirical + (1 - empiricalWeight) * neuralBaseline;
  }
  scores.sort((a, b) => b.probability - a.probability || a.password.localeCompare(b.password, 'en'));
  return { ranking: scores.map(item => item.password), scores, model, attack, empiricalWeight };
}

export function wilsonInterval(successes, total, z = 1.95996398454) {
  if (!total) return [0, 1];
  const p = successes / total;
  const denominator = 1 + z * z / total;
  const center = (p + z * z / (2 * total)) / denominator;
  const radius = z * Math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator;
  return [Math.max(0, center - radius), Math.min(1, center + radius)];
}

/** Missing passwords are right censored at K+1, never treated as cracked. */
export function evaluateRanking(ranking, samples, budgets = [10, 30, 100, 300, 1000, 3000]) {
  const ranks = new Map(ranking.map((password, index) => [password, index + 1]));
  const actualRanks = samples.map(item => ranks.get(toPassword(item)) ?? Infinity);
  const coverage = actualRanks.filter(Number.isFinite).length;
  const limit = ranking.length;
  const validBudgets = [...new Set(budgets.filter(value => value > 0).map(value => Math.min(Math.floor(value), limit)))].sort((a, b) => a - b);
  return {
    total: samples.length,
    candidateCount: limit,
    coverage: coverage / Math.max(1, samples.length),
    uncovered: samples.length - coverage,
    // E[min(G, K+1)] is a lower bound on E[G] if any observations are censored.
    restrictedMeanGuesses: actualRanks.reduce((sum, rank) => sum + Math.min(rank, limit + 1), 0) / Math.max(1, samples.length),
    restrictedMeanLabel: 'E[min(G, K+1)]; right-censored outside the public candidate universe',
    points: validBudgets.map(budget => {
      const cracked = actualRanks.filter(rank => rank <= budget).length;
      return { budget, cracked, rate: cracked / Math.max(1, samples.length), interval: wilsonInterval(cracked, samples.length) };
    }),
  };
}

/** Head membership is learned exclusively on the training partition. */
export function selectHead(train, mass = 0.7) {
  const sorted = [...frequencyCounts(train)].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'en'));
  const head = new Set();
  let cumulative = 0;
  const target = Math.max(0, Math.min(1, mass));
  for (const [password, count] of sorted) {
    if (cumulative / Math.max(1, train.length) >= target) break;
    head.add(password);
    cumulative += count;
  }
  return { head, coveredMass: cumulative / Math.max(1, train.length), rank: head.size, target };
}

export function transformSamples(samples, { policy = 'original', head = new Set(), seed = 123, adoption = 1 } = {}) {
  const random = seededRandom(seed);
  const uniformWord = () => PHRASE_WORDS[Math.floor(random() * PHRASE_WORDS.length)];
  return samples.map((item, index) => {
    const password = toPassword(item);
    let next = password;
    if (policy === 'fixed') next = password + '2026!';
    if (policy === 'diversified' && head.has(password) && random() < adoption) {
      next = `${uniformWord()}-${uniformWord()}-${uniformWord()}`;
    }
    return { id: typeof item === 'string' ? index : item.id, password: next };
  });
}

export function policyCandidateSpace(policy, head, adoption = 1) {
  const original = originalCandidateSpace();
  if (policy === 'fixed') return original.map(password => password + '2026!');
  if (policy === 'diversified') {
    return [...original.filter(password => adoption < 1 || !head.has(password)), ...phraseCandidateSpace()];
  }
  return original;
}

function testOracle(samples, budgets) {
  const counts = [...frequencyCounts(samples)].sort((a, b) => b[1] - a[1]);
  return evaluateRanking(counts.map(([password]) => password), samples, budgets);
}

/**
 * Full experiment. Validation is reserved for extension; no optimization uses test.
 * Every informed attacker retrains on policy-transformed training users.
 */
export function runRedTeamExperiment({ size = 9000, seed = 42, exponent = 1.08, headMass = 0.7, adoption = 1, attack = 'hybrid', budgets = [10, 30, 100, 300, 1000, 3000] } = {}) {
  const started = globalThis.performance?.now() ?? Date.now();
  const data = createSyntheticDataset({ size, seed, exponent });
  const headSelection = selectHead(data.train, headMass);
  const baselineAttacker = rankCandidates(data.train, data.candidates, { attack });
  const rows = [];
  for (const policy of ['original', 'fixed', 'diversified']) {
    const train = transformSamples(data.train, { policy, head: headSelection.head, seed: seed + 11, adoption });
    const test = transformSamples(data.test, { policy, head: headSelection.head, seed: seed + 29, adoption });
    const candidates = policyCandidateSpace(policy, headSelection.head, adoption);
    const informed = policy === 'original' ? baselineAttacker : rankCandidates(train, candidates, { attack });
    const adaptive = evaluateRanking(informed.ranking, test, budgets);
    const frozen = evaluateRanking(baselineAttacker.ranking, test, budgets);
    const counts = [...frequencyCounts(test).values()].sort((a, b) => b - a);
    rows.push({
      policy,
      label: { original: '原始分布', fixed: '统一添加 2026!', diversified: '头部随机短语' }[policy],
      adaptive,
      frozen,
      empiricalOracle: testOracle(test, budgets),
      oracleWarning: 'Test-frequency oracle is descriptive and optimistic; it is not a trained attacker result',
      top1Mass: (counts[0] || 0) / test.length,
      uniqueRatio: counts.length / test.length,
      meanLength: test.reduce((sum, item) => sum + item.password.length, 0) / test.length,
      changedFraction: test.filter((item, index) => item.password !== data.test[index].password).length / test.length,
    });
  }
  return {
    rows,
    head: { ...headSelection, head: undefined },
    metadata: {
      ...data.metadata,
      trainSize: data.train.length,
      validationSize: data.validation.length,
      testSize: data.test.length,
      attack: attack === 'hybrid' ? '65% empirical frequency + 35% character trigram probability' : attack,
      policy: 'A toy 16-word phrase grammar; real deployment requires a much larger audited word list and cryptographic randomness',
      assumptions: ['Public synthetic grammar', 'Independent users; repeated password strings are allowed across splits', 'Attacker knows policy and trains on independently transformed training users', 'Per-budget Wilson intervals are conditional on one trained model; not simultaneous bands'],
      fixedRuleInvariant: 'Appending a known fixed suffix is injective, so it preserves the true frequency distribution and ideal Top-B mass',
      runtimeMs: (globalThis.performance?.now() ?? Date.now()) - started,
    },
  };
}

/** In-memory synthetic model for the interactive candidate input. */
export function createRiskEvaluator(options = {}) {
  const data = createSyntheticDataset({ size: 5000, ...options });
  const { model, ranking } = rankCandidates(data.train, data.candidates, { attack: 'hybrid' });
  const rankMap = new Map(ranking.map((password, index) => [password, index + 1]));
  const counts = frequencyCounts(data.train);
  return password => {
    const ai = scoreNgram(model, password);
    const rank = rankMap.get(password) ?? null;
    const commonPatterns = [];
    if (/\d{2,}$/.test(password)) commonPatterns.push('数字后缀');
    if (/20[0-9]{2}/.test(password)) commonPatterns.push('年份结构');
    if (/^[A-Z][a-z]+/.test(password)) commonPatterns.push('首字母大写');
    if (/(.)\1{2,}/.test(password)) commonPatterns.push('重复字符');
    if (password.length < 10) commonPatterns.push('长度较短');
    return {
      ...ai,
      rank,
      inCandidateSpace: rank !== null,
      observedTrainCount: counts.get(password) || 0,
      candidateCount: ranking.length,
      patterns: commonPatterns,
      empiricalProbability: (counts.get(password) || 0) / data.train.length,
      riskLabel: rank === null ? '超出合成模型覆盖范围' : rank <= 30 ? '合成分布头部' : rank <= 150 ? '合成分布中部' : '合成分布尾部',
      note: rank === null ? '未被候选空间覆盖不代表安全；不提供绝对猜测成本。' : '排名仅相对于公开合成候选集。',
    };
  };
}

/** User-readable suggestions: no unvalidated numerical security gains. */
export function recommendStrategies(password, evaluate = createRiskEvaluator()) {
  const assessment = evaluate(password);
  return {
    assessment,
    strategies: [
      { id: 'random-phrase', title: '独立随机选择多个词', example: 'birch-ocean-quartz', burden: '需要记忆新词组', reason: '减少热门词根复用；示例仅用于演示，不应作为真实口令。', claim: '可在红蓝实验中检验分布变化', supported: true },
      { id: 'manager', title: '使用密码管理器生成独立口令', example: null, burden: '需要使用管理器', reason: '独立生成，避免从原口令做可预测编辑。', claim: '当前原型未测量实际可用性', supported: false },
      { id: 'fixed', title: '对照：统一追加固定后缀', example: password + '2026!', burden: '修改较少', reason: '攻击者知道规则时可直接映射猜测；理想 Top-B 风险不变。', claim: '用作负面对照', supported: true },
    ],
  };
}
