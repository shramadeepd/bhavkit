# bhavkit data-quality report — idx

- generated: 2026-09-18T23:55:45
- range: 2024-01-01 .. 2024-01-31
- gaps: 18 missing, 0 errors, 0 unknown holidays

## Monthly coverage

| month | expected | data days | holidays | errors | coverage |
| ------ | -------: | --------: | -------: | -----: | -------: |
| 2024-01 | 21 | 3 | 0 | 0 | 14.29% |

## Gaps

Missing attempts (weekdays with no record):
 - 2024-01-01, 2024-01-02, 2024-01-08, 2024-01-09, 2024-01-10, 2024-01-11, 2024-01-12, 2024-01-15, 2024-01-16, 2024-01-17, 2024-01-18, 2024-01-19, 2024-01-23, 2024-01-24, 2024-01-25, 2024-01-29, 2024-01-30, 2024-01-31

## Anomalies

### EXTREME_MOVE (7)

| symbol | date | prev_close | close |
| --- | --- | --- | --- |
| ALLCARGO | 2024-01-02 | 329.05 | 90.1 |
| NESTLEIND | 2024-01-05 | 27116.4 | 2666.4 |
| COCHINSHIP | 2024-01-10 | 1338.0 | 802.8 |
| JYOTICNC | 2024-01-16 | 331.0 | 434.2 |
| OFSS | 2024-01-18 | 5086.2 | 6545.5 |

### ZERO_VOLUME_WITH_TRADES (0)

### NEGATIVE_PRICE (0)

### DELIVERY_MISMATCH (0)

## Equity master drift

EQ symbols with bars but missing from the master: AARVEEDEN, ABSLBANETF, ABSLLIQUID, ABSLNN50ET, ACLGATI, ADORWELD, AEGISCHEM, AHL, AKZOINDIA, ALLSEC, ALPHAETF, ALPL30IETF, ALPSINDUS, AMIORG, ATFL, AUTOBEES, AUTOIETF, AXISBNKETF, AXISBPSETF, AXISCETF, AXISGOLD, AXISHCETF, AXISILVER, AXISNIFTY, AXISTECETF, AXSENSEX, BANKBEES, BANKBETF, BANKETF, BANKIETF, BARBEQUE, BBETF0432, BBNPPGOLD, BFSI, BSE500IETF, BSLGOLDETF, BSLNIFTY, BSLSENETFG, CAREERP, CENTURYTEX, CIGNITITEC, COMMOIETF, CONSUMBEES, CONSUMIETF, CPSEETF, CREATIVE, DEEPENR, DHANI, DIL, DIVOPPBEES

## Cross-dataset coverage

| table | days | rows | first | last |
| --- | ---: | ---: | --- | --- |
| index_daily | 3 | 324 | 2024-01-03 | 2024-01-05 |
| fo_daily | 3 | 174468 | 2024-01-03 | 2024-01-05 |
| deliverable_daily | 3 | 7787 | 2024-01-03 | 2024-01-05 |
