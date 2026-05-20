//! Lumen load test driver.
//!
//! Uses Goose (Rust load-testing framework, async, Locust-inspired) to fire
//! concurrent `/api/search` requests against the deployed Databricks App,
//! measuring throughput and full latency percentiles.
//!
//! ## Usage
//!
//!     LUMEN_TOKEN=$(databricks auth token --profile azure-video \
//!         | jq -r .access_token) \
//!     cargo run --release -- \
//!         --host https://lumen-recommender-7405604561430667.7.azure.databricksapps.com \
//!         -u 20 -r 5 -t 2m \
//!         --report-file report.html --no-reset-metrics
//!
//! Goose flags (a few useful ones):
//!   -u, --users <N>          concurrent users
//!   -r, --hatch-rate <N>     users started per second during ramp-up
//!   -t, --run-time <T>       e.g. 30s / 5m / 1h
//!   --no-reset-metrics       keep ramp-up samples (default discards them)
//!   --report-file <PATH>     write an HTML report
//!   --request-log <PATH>     write per-request JSONL log
//!
//! Goose reports mean / median / p50 / p75 / p95 / p98 / p99 / p99.9 / max
//! per request type, plus aggregated throughput and error counts.

use std::env;

use goose::prelude::*;
use rand::seq::SliceRandom;
use serde_json::json;

mod queries;
use queries::QUERIES;

/// Mode mix: 70% semantic, 30% hybrid (representative of an app's traffic
/// pattern — most queries don't include keyword hints).
const SEMANTIC_WEIGHT: u8 = 70;

async fn search(user: &mut GooseUser) -> TransactionResult {
    // Scope the (non-Send) ThreadRng so it's dropped before any `.await`.
    let (query, mode) = {
        let mut rng = rand::thread_rng();
        let q = QUERIES.choose(&mut rng).copied().unwrap_or("chair");
        let m = if rand::random::<u8>() % 100 < SEMANTIC_WEIGHT {
            "semantic"
        } else {
            "hybrid"
        };
        (q, m)
    };

    let body = json!({
        "q": query,
        "mode": mode,
        "limit": 20,
    });

    let token = env::var("LUMEN_TOKEN").unwrap_or_default();

    // Build an explicit request so we can attach the auth header.
    let request_builder = user
        .get_request_builder(&GooseMethod::Post, "/api/search")?
        .bearer_auth(&token)
        .json(&body);

    // Name the request after the mode so Goose tracks semantic/hybrid stats
    // separately in the final report.
    let goose_request = GooseRequest::builder()
        .name(if mode == "hybrid" { "search:hybrid" } else { "search:semantic" })
        .set_request_builder(request_builder)
        .build();

    let mut response = user.request(goose_request).await?;

    // Mark non-2xx as failures and capture a short body snippet to help
    // diagnose issues (token expiry, 500s, etc.).
    if let Ok(r) = response.response.as_ref() {
        let status = r.status();
        if !status.is_success() {
            let snippet = response
                .response
                .as_mut()
                .map(|_| ())
                .ok();
            let _ = snippet;
            return user
                .set_failure(
                    &format!("search returned HTTP {status}"),
                    &mut response.request,
                    None,
                    None,
                )
                .map(|_| ());
        }
    }

    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), GooseError> {
    if env::var("LUMEN_TOKEN").is_err() {
        eprintln!(
            "warning: LUMEN_TOKEN is not set — requests will be unauthenticated.\n\
             Export it before running:\n  \
             export LUMEN_TOKEN=$(databricks auth token --profile azure-video | jq -r .access_token)"
        );
    }

    GooseAttack::initialize()?
        .register_scenario(
            scenario!("Search")
                .register_transaction(transaction!(search).set_name("search")),
        )
        .execute()
        .await?;

    Ok(())
}
