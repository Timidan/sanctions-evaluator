#!/usr/bin/env bash
# Download the public sanctions lists into data/raw/ and record when.
set -euo pipefail
cd "$(dirname "$0")/.." && mkdir -p data/raw && cd data/raw
date -u +%FT%TZ > DOWNLOADED_AT
O=https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports
for f in SDN.CSV ALT.CSV ADD.CSV SDN_COMMENTS.CSV CONS_PRIM.CSV CONS_ALT.CSV; do curl -fsSL -o "$f" "$O/$f"; done
curl -fsSL -o consolidated.xml https://scsanctions.un.org/resources/xml/en/consolidated.xml
curl -fsSL -o eu_fsf.csv "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"
curl -fsSL -o uk_sanctions_list.csv https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv
sha256sum * > SHA256SUMS.local
