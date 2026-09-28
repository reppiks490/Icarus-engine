"""H-LOC P4 null: is the lambda's held-out gain distinguishable from noise?

Two tests on the same surrogates (`shuffle_bars`, context rebuilt FROM the
surrogate so the real sequence cannot leak back in):

  1. absolute -- observed net at L* vs surrogate nets at L* (the usual null:
     does this configuration beat a sequence-destroyed tape at all)
  2. paired   -- observed (net at L*) - (net at L=+1) vs the same difference
     measured on every surrogate. This is the test that is actually about the
     lambda: a surrogate tape has no location structure, so if the delta is
     real it should not reproduce there.
"""
import sys, random, statistics as st, time, json
sys.path.insert(0, '/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.backtest import shuffle_bars
from icarus.data import load_csv
from tools.htf_context import ContextProvider
from tools.validate_pulse import run_pulse

SPLIT = datetime(2025, 10, 1, tzinfo=timezone.utc)


def main(tf, lam_star, span="HOLD", runs=60, mode="ATR-Based", seed=3):
    bars = load_csv(f"/home/user/Icarus-engine/data/mnq_{tf}m_full.csv")
    seg = ([b for b in bars if b.ts < SPLIT] if span == "TUNE"
           else [b for b in bars if b.ts >= SPLIT] if span == "HOLD" else bars)
    ctx = ContextProvider(seg, f"{tf}m")
    obs_star = run_pulse(seg, tf_minutes=tf, tpsl_mode=mode, context=ctx, vwap_vote_lambda=lam_star)
    obs_base = run_pulse(seg, tf_minutes=tf, tpsl_mode=mode, context=ctx, vwap_vote_lambda=1.0)
    d_obs = obs_star["net"] - obs_base["net"]
    print(f"pulse.py {tf}m {mode} {span}: L*={lam_star:+.2f} net=${obs_star['net']:+,.0f} "
          f"(n={obs_star['trades']}, exp=${obs_star['expectancy']:+.2f})  "
          f"L=+1 net=${obs_base['net']:+,.0f} (n={obs_base['trades']}, "
          f"exp=${obs_base['expectancy']:+.2f})  delta=${d_obs:+,.0f}")
    sys.stdout.flush()

    rng = random.Random(seed)
    nets, deltas = [], []
    for k in range(runs):
        t0 = time.time()
        sur = shuffle_bars(seg, rng)
        sctx = ContextProvider(sur, f"{tf}m")
        a = run_pulse(sur, tf_minutes=tf, tpsl_mode=mode, context=sctx, vwap_vote_lambda=lam_star)
        b = run_pulse(sur, tf_minutes=tf, tpsl_mode=mode, context=sctx, vwap_vote_lambda=1.0)
        nets.append(a["net"])
        deltas.append(a["net"] - b["net"])
        if (k + 1) % 10 == 0:
            print(f"   {k+1}/{runs}  ({time.time()-t0:.0f}s/run)  "
                  f"nets>=obs {sum(1 for x in nets if x >= obs_star['net'])}  "
                  f"deltas>=obs {sum(1 for x in deltas if x >= d_obs)}")
            sys.stdout.flush()
    p_abs = (sum(1 for x in nets if x >= obs_star["net"]) + 1) / (runs + 1)
    p_del = (sum(1 for x in deltas if x >= d_obs) + 1) / (runs + 1)
    print(f"ABSOLUTE  null median ${st.median(nets):+,.0f}  best ${max(nets):+,.0f}  "
          f"p={p_abs:.4f}  (floor {1/(runs+1):.4f})")
    print(f"PAIRED    delta null median ${st.median(deltas):+,.0f}  best ${max(deltas):+,.0f}  "
          f"p={p_del:.4f}  (floor {1/(runs+1):.4f})")
    json.dump({"observed_star": obs_star, "observed_base": obs_base, "nets": nets,
               "deltas": deltas, "p_abs": p_abs, "p_delta": p_del, "tf": tf,
               "lam": lam_star, "span": span},
              open(f"/tmp/claude-0/-home-user-Icarus-engine/134e69c0-9376-5c62-9fa5-dfe829f5f315/"
                   f"scratchpad/p4null_{tf}_{span}.json", "w"))


if __name__ == "__main__":
    main(int(sys.argv[1]), float(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "HOLD",
         int(sys.argv[4]) if len(sys.argv) > 4 else 60)
