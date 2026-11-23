### Task: Server-Side Downsampling for 100k Monte Carlo Efficient Frontier Cloud

**Goal:** Run the full 100,000-portfolio Monte Carlo simulation on the backend for statistical accuracy while reducing HTTP payload size and frontend chart lag by downsampling points during response serialization.

**Implementation Requirements:**
1. **Keep Full Simulation:** Allow the solver/simulation engine to execute all 100,000 random portfolio runs without raising or lowering the frontend payload cap.
2. **Downsample in `_frontier_to_response`:** Modify `_frontier_to_response` to return a **stratified sample of ~5,000–10,000 scatter points** (binned across volatility/return quantiles so the cloud's outer hull and density distribution remain visually intact) rather than returning all 100k points or taking a naive slice.
3. **Preserve Marked Portfolios:** Explicitly retain and include all key reference portfolios (e.g., Max Sharpe / Tangency, Global Minimum Variance, Equal-Weight, and Efficient Frontier curve vertices) so they are never dropped by sampling.