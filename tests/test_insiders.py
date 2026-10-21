import io
import zipfile
from datetime import date

from market.data.insiders import form4_paths, parse_dataset, parse_form4, quarter_bounds, quarters

FORM4 = """<SEC-DOCUMENT>junk<XML>
<ownershipDocument>
  <issuer><issuerCik>0000320193</issuerCik><issuerName>Apple Inc.</issuerName><issuerTradingSymbol>aapl</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0001234567</rptOwnerCik><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>true</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-14</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>200.5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-14</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>10</value></transactionShares>
        <transactionPricePerShare><value>201</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument></XML></SEC-DOCUMENT>"""


def test_parse_form4_keeps_open_market_purchases():
    rows = parse_form4(FORM4, "0001-26-1", date(2026, 10, 16))
    assert len(rows) == 1
    r = rows[0]
    assert r["issuer_cik"] == 320193 and r["ticker"] == "AAPL" and r["owner_cik"] == 1234567
    assert r["is_director"] and r["is_officer"] and r["officer_title"] == "CEO"
    assert r["value"] == 200_500 and r["shares_after"] == 5000 and r["source"] == "xml"


def _zip(tables: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in tables.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_parse_dataset_without_the_newer_plan_column():
    raw = _zip({
        "NONDERIV_TRANS.tsv": "ACCESSION_NUMBER\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\tTRANS_PRICEPERSHARE\t"
                              "TRANS_ACQUIRED_DISP_CD\tSHRS_OWND_FOLWNG_TRANS\tDIRECT_INDIRECT_OWNERSHIP\n"
                              "a\t03-MAR-2021\tP\t100\t10.5\tA\t1100\tD\n"
                              "a\t03-MAR-2021\tM\t50\t0\tA\t1150\tD\n",
        "SUBMISSION.tsv": "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERNAME\tISSUERTRADINGSYMBOL\n"
                          "a\t05-MAR-2021\t4\t0000000042\tAcme\tacme\n",
        "REPORTINGOWNER.tsv": "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\n"
                              "a\t0000000007\tRoe Rich\tDirector,Officer\tCFO\n",
    })
    frame = parse_dataset(raw)
    assert len(frame) == 1
    r = frame.iloc[0]
    assert r["issuer_cik"] == 42 and r["ticker"] == "ACME" and r["value"] == 1050
    assert r["filed"] == date(2021, 3, 5) and r["is_officer"] and not r["plan_10b5_1"]


def test_quarters_and_index_paths():
    assert quarters(date(2021, 7, 1)) == ["2021q1", "2021q2", "2021q3"]
    assert quarter_bounds("2026q1") == (date(2026, 1, 1), date(2026, 3, 31))
    idx = ("4          APPLE INC   320193   20261016   edgar/data/320193/0001-26-1.txt\n"
           "4          DOE JANE    1234567  20261016   edgar/data/320193/0001-26-1.txt\n"
           "4          OTHER CO    999      20261016   edgar/data/999/0002-26-1.txt\n"
           "8-K        APPLE INC   320193   20261016   edgar/data/320193/0003-26-1.txt\n")
    assert form4_paths(idx, {320193}) == {("0001-26-1", "edgar/data/320193/0001-26-1.txt")}
