-- sieve_terms: build Xenakis sieve terms from two sampled dimensions.
--
--   modulos   -- sample_moduli(params, terms, seed, mmax): moduli drawn from a
--                hierarchical distribution — K peak centers sampled from a
--                lognormal landscape (center, spread), sampled weights
--                (dominance -> one big peak + little ones), Gaussian width;
--                `terms` integers drawn from the resulting mixture.
--   residuals -- draw_residues(M, density, concentration, seed): which residue
--                classes of modulus M are active, drawn from a von-Mises-like
--                distribution over [0,M). Mirrors the OBS palette shader's
--                model so the two instruments feel related.
--
-- Pure Lua, no crow API — unit-testable with plain `lua`.

SieveTerms = {}

-- ---- helpers ---------------------------------------------------------------

-- Deterministic hash in [0,1) from INTEGER inputs. Integer LCG chain, all
-- intermediates < 2^31: exact on crow, whose Lua is built with 32-bit
-- numbers (float32 + int32). A float-based frac(big*x) hash silently
-- returns ~0 there — float32 has 24 mantissa bits — which zeroes every
-- draw. Callers must pass integers.
local function hash01(a, b, c)
  local n = (a * 8121 + b * 28411 + c * 13849) % 65536
  n = (n * 9301 + 49297) % 65536
  n = (n * 9301 + 49297) % 65536
  return (n + 0.5) / 65536.0
end

-- ---- residuals -------------------------------------------------------------

-- Which residue classes of modulus M are active. Each class r in [0,M) gets a
-- von-Mises weight w(r) = exp(kappa * cos(2pi*(r/M - offset))), peaked near
-- `offset` when concentration is high, flat when it's ~0. A class is active
-- when a seeded hash falls under density * w_norm(r):
--   density        -- 0..1, roughly the fraction of classes that fire
--   concentration  -- 0..1, 0 = residues spread evenly, 1 = clustered
--   seed           -- 0..1, slides `offset` and re-rolls membership
-- Always returns at least one class (the strongest) so a term never goes dark.
function SieveTerms.draw_residues(M, density, concentration, seed)
  M = math.max(1, math.floor(M + 0.5))
  density = math.max(0.0, math.min(1.0, density or 0.5))
  concentration = math.max(0.0, math.min(1.0, concentration or 0.0))
  seed = seed or 0.0

  local kappa = concentration * 6.0          -- 0 (flat) .. 6 (sharp)
  local offset = seed - math.floor(seed)
  local TAU = 2 * math.pi

  -- weights + peak (for normalisation so density reads consistently)
  local w, wmax = {}, 1e-9
  for r = 0, M - 1 do
    local val = math.exp(kappa * math.cos(TAU * (r / M - offset)))
    w[r] = val
    if val > wmax then wmax = val end
  end

  local residues = {}
  local best_r, best_score = 0, -1
  for r = 0, M - 1 do
    local wn = w[r] / wmax                    -- 0..1
    local score = density * wn
    if hash01(r, M, math.floor(seed * 1000)) < score then
      residues[#residues + 1] = r
    end
    if wn > best_score then best_score, best_r = wn, r end
  end
  if #residues == 0 then residues = { best_r } end
  return residues
end

-- Residues for an EXPLICIT moduli list: every active residue of every modulus
-- becomes one UNION term, so a step hits if it matches any class. The union
-- saturates fast (each modulus covering fraction p gives total 1-(1-p)^n), so
-- we invert: to make the *total* onset fraction ~= `density`, each modulus
-- covers per_mod = 1-(1-density)^(1/n). Without this, density 0.35 over 3
-- moduli already fires ~72% of ticks.
function SieveTerms.residues_for(moduli, density, concentration, seed)
  local n = #moduli
  density = math.max(0.0, math.min(1.0, density or 0.5))
  local per_mod = (n > 1) and (1 - (1 - density) ^ (1 / n)) or density
  local pairs_ = {}
  for _, M in ipairs(moduli) do
    for _, I in ipairs(SieveTerms.draw_residues(M, per_mod, concentration, seed)) do
      pairs_[#pairs_ + 1] = { M, I }
    end
  end
  return pairs_
end

-- ---- hierarchical moduli sampling ------------------------------------------
-- Two-level generative model over the (log) modulus axis:
--   level 1: d(x) — a lognormal landscape (center, spread) from which K peak
--            centers are SAMPLED; each peak also samples a weight, with
--            `dominance` skewing toward one-large-peak-plus-little-ones.
--   level 2: the Gaussian mixture f(m) = sum w_k * G(mu_k, width) on integer
--            moduli 2..mmax (log distance, so width is a ratio).
--   level 3: `terms` moduli are sampled from f without replacement.
-- Everything is drawn via seeded hashes — same seed, same moduli.

local function gauss01(a, b)
  local u1 = math.max(hash01(a, 1, b), 1e-9)
  local u2 = hash01(a, 2, b)
  return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
end

-- p: {center, spread, n_peaks, width, dominance}; returns moduli (sorted), peaks
function SieveTerms.sample_moduli(p, terms, seed, mmax)
  mmax = mmax or 96
  local K = math.max(1, math.floor((p.n_peaks or 3) + 0.5))
  local sd = math.floor((seed or 0) * 1000)
  local peaks, wsum = {}, 0
  for k = 1, K do
    local mu = (p.center or 8) * math.exp(gauss01(k, sd) * (p.spread or 0.5))
    local w = hash01(k, 3, sd) ^ (1 + 6 * (p.dominance or 0))
    peaks[k] = { mu = math.max(2, math.min(mu, mmax)), w = w }
    wsum = wsum + w
  end
  for _, pk in ipairs(peaks) do pk.w = pk.w / math.max(wsum, 1e-9) end

  local width = math.max(0.02, p.width or 0.25)
  local dens = {}
  for m = 2, mmax do
    local f = 0
    for _, pk in ipairs(peaks) do
      local d = math.log(m) - math.log(pk.mu)
      f = f + pk.w * math.exp(-(d * d) / (2 * width * width))
    end
    dens[m] = f
  end

  local moduli = {}
  for t = 1, math.max(1, math.floor((terms or 3) + 0.5)) do
    local Z = 0
    for m = 2, mmax do if dens[m] then Z = Z + dens[m] end end
    if Z < 1e-12 then break end
    local r = hash01(t, 4, sd) * Z
    local acc = 0
    for m = 2, mmax do
      if dens[m] then
        acc = acc + dens[m]
        if acc >= r then moduli[#moduli + 1] = m; dens[m] = nil; break end
      end
    end
  end
  table.sort(moduli)
  return moduli, peaks
end
