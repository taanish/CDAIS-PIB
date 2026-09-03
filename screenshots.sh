#!/bin/bash
# Regenerate the four deliverable views for workplan step 1 (2024-2026),
# straight out of corpus.db. Every number here is a stored view — nothing is
# computed on the fly, so a screenshot of this output IS the catalogue.
#
#   ./screenshots.sh            # all four, to the terminal
#
# The underlying views (query any of them directly):
#   v_accepted_keywords   the vocabulary that defines an "AI mention"
#   v_keyword_yield       releases + mentions each keyword accounts for
#   v_hits_by_year        AI releases / mentions per year, with a TOTAL row
#   v_ai_pool             one row per catalogued release (deduplicated)
#   v_expansion_tree      extended-term candidates under the seed that found them
cd "$(dirname "$0")" || exit 1
DB=corpus.db
q() { sqlite3 -header -column "$DB" "$1"; }

echo
echo "###############################################################################"
echo "# 1 + 3.  AI HITS / MATCHED RELEASES PER YEAR            (view: v_hits_by_year)"
echo "###############################################################################"
q "SELECT year,
          ai_releases AS distinct_releases,
          ai_mentions AS total_keyword_mentions
   FROM v_hits_by_year;"
echo "  distinct_releases = releases with >=1 AI keyword (the catalogue)"
echo "  total_keyword_mentions = sum of keyword occurrences (a release can hit many)"

echo
echo "###############################################################################"
echo "# 2.  ACCEPTED KEYWORD LIST                          (view: v_accepted_keywords)"
echo "###############################################################################"
q "SELECT term, round, reviewed_by AS origin, channel,
          releases_matched
   FROM v_accepted_keywords;"
echo "  round 0 = your K1 seed list;  round 1 = terms accepted in earlier review"

echo
echo "###############################################################################"
echo "# 4.  RELEASES IDENTIFIED PER KEYWORD                    (view: v_keyword_yield)"
echo "###############################################################################"
q "SELECT term, releases_matched, total_mentions, round
   FROM v_keyword_yield;"

echo
echo "###############################################################################"
echo "# BONUS.  EXTENDED-TERM CANDIDATES PER SEED  (workplan 1.2.2, awaiting review)"
echo "#         (view: v_expansion_tree — promote with:  expand.py accept \"term\")"
echo "###############################################################################"
q "SELECT seed, extended_term, channel, releases_matched
   FROM v_expansion_tree
   WHERE status='candidate' AND releases_matched >= 15
   ORDER BY seed, releases_matched DESC;"
echo
echo "candidate pool: $(sqlite3 "$DB" "SELECT COUNT(*) FROM terms WHERE status='candidate';") extended terms surfaced (>=15-release ones shown above)"
echo
