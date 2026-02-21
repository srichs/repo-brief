"""Backward-compatible exports for the historical ``repo_brief.repo_brief`` module."""

from . import agents_workflow, budget, cli, github_client

DeepDiveAgent = agents_workflow.DeepDiveAgent
OverviewAgent = agents_workflow.OverviewAgent
ReadingPlanAgent = agents_workflow.ReadingPlanAgent
fetch_files = agents_workflow.fetch_files
fetch_repo_context = agents_workflow.fetch_repo_context
get_final_text = agents_workflow.get_final_text
run_briefing_loop = agents_workflow.run_briefing_loop

Pricing = budget.Pricing
estimate_cost_usd = budget.estimate_cost_usd
usage_totals = budget.usage_totals

build_parser = cli.build_parser
main = cli.main

_parse_github_repo_url = github_client.parse_github_repo_url
_gh_headers = github_client.gh_headers
_safe_get_json = github_client.safe_get_json
_truncate = github_client.truncate
_build_tree_index = github_client.build_tree_index
_tree_summary = github_client.tree_summary
_pick_key_files = github_client.pick_key_files
_fetch_repo_tree = github_client.fetch_repo_tree
_fetch_file_content = github_client.fetch_file_content
_fetch_repo_context_impl = github_client.fetch_repo_context_impl
_fetch_files_impl = github_client.fetch_files_impl
_json_or_fallback = agents_workflow.json_or_fallback
_validate_price_overrides = budget.validate_price_overrides
_render_output = cli.render_output
_write_output = cli.write_output
