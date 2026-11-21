"""Generates the synthetic Larkveil Residences deal-room PDF pack.

All figures are fictional and internally coherent EXCEPT the deliberately
planted inconsistencies documented in eval/seeded_issues.json:

  1. Acquisition fee: OM says 2.0%, PPM fee schedule says 2.75% (verifiable).
  2. Exit cap rate: pro forma uses 5.0%, market study shows 5.5-6.0%
     prevailing (verifiable contradiction; "is 5.0% reasonable" is
     judgment_required).
  3. Occupancy: rent roll shows ~87.8% in-place, pro forma Year-1 assumes
     94% stabilized occupancy with no lease-up cost bridge (verifiable).
  4. Track record spin: sponsor bio's "never lost investor capital" framing
     glosses over a return-of-capital-only prior exit (judgment_required).

Run: uv run python data/generate_cre_dealroom.py
"""

from pathlib import Path

from fpdf import FPDF

OUT_DIR = Path(__file__).parent / "cre_dealroom"
OUT_DIR.mkdir(parents=True, exist_ok=True)


class Doc(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 6, "SYNTHETIC DEMO DATA - fictional companies, people and properties",
                  align="C")


def new_doc():
    pdf = Doc()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    return pdf


def title(pdf, text):
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", size=11)


def h2(pdf, text):
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)


def p(pdf, text):
    pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def kv(pdf, label, value):
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, f"{label}:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, str(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


# ---------------------------------------------------------------------------
# 1. Offering Memorandum
# ---------------------------------------------------------------------------
def gen_om():
    pdf = new_doc()
    title(pdf, "Larkveil Residences\nOffering Memorandum")
    p(pdf, "Prepared for investors. Confidential - synthetic demo data.")

    h2(pdf, "Property Overview")
    kv(pdf, "Property", "Larkveil Residences")
    kv(pdf, "Address", "4200 Halvercott Rd, Marrowdale (fictional city), North Marrowdale submarket")
    kv(pdf, "Units", "148")
    kv(pdf, "Strategy", "Value-add multifamily - unit renovation, amenity upgrade, rent growth")
    kv(pdf, "Year built", "1998")

    h2(pdf, "Transaction Summary")
    kv(pdf, "Purchase price", "$27,800,000")
    kv(pdf, "Target hold period", "5 years")
    kv(pdf, "Projected IRR (5-yr, LP)", "17.2%")
    kv(pdf, "Projected MOIC", "1.9x")

    h2(pdf, "Business Plan")
    p(pdf, "Sponsor plans to execute a unit-by-unit renovation program across "
            "the 148-unit community, upgrading kitchens, flooring, and fixtures "
            "on turnover, alongside clubhouse and amenity upgrades. The business "
            "plan targets stabilized occupancy of 94% by the end of Year 1, "
            "supporting rent growth from the current in-place average toward "
            "renovated market rents.")

    h2(pdf, "Fee Summary")
    p(pdf, "Sponsor fees are structured to align incentives with investors "
            "across the hold period.")
    kv(pdf, "Acquisition fee", "2.0% of purchase price")
    kv(pdf, "Asset management fee", "1.5% of invested equity, annually")
    kv(pdf, "Disposition fee", "1.0% of gross sale price")
    p(pdf, "See the PPM for the complete, governing fee schedule and risk factors.")

    h2(pdf, "Sources & Uses")
    kv(pdf, "Total uses", "$31,120,000 (acquisition $27,800,000 + capex $2,900,000 + closing costs $420,000)")
    kv(pdf, "Senior loan", "$20,200,000")
    kv(pdf, "LP equity", "$9,920,000")
    kv(pdf, "GP co-investment", "$1,000,000")

    pdf.output(str(OUT_DIR / "01_offering_memorandum.pdf"))


# ---------------------------------------------------------------------------
# 2. PPM excerpt
# ---------------------------------------------------------------------------
def gen_ppm():
    pdf = new_doc()
    title(pdf, "Larkveil Residences\nPrivate Placement Memorandum (Excerpt)")
    p(pdf, "This excerpt covers the fee schedule, distribution waterfall, and "
            "select risk factors. Full PPM available upon request.")

    h2(pdf, "Fee Schedule")
    p(pdf, "The following fees are payable to the Sponsor or its affiliates:")
    kv(pdf, "Acquisition fee", "2.75% of purchase price, payable at closing")
    kv(pdf, "Asset management fee", "1.5% of invested equity, payable annually")
    kv(pdf, "Disposition fee", "1.0% of gross sale price, payable at disposition")
    kv(pdf, "Financing fee", "0.5% of loan proceeds, payable at closing")

    h2(pdf, "Distribution Waterfall")
    p(pdf, "Distributable cash is allocated in the following order of priority:")
    p(pdf, "1. 8.0% cumulative preferred return to LP investors.")
    p(pdf, "2. Return of LP invested capital.")
    p(pdf, "3. 70% LP / 30% GP until LP achieves a 14% IRR.")
    p(pdf, "4. 60% LP / 40% GP thereafter.")

    h2(pdf, "Selected Risk Factors")
    p(pdf, "- Real estate investments are illiquid; there is no secondary market "
            "for LP interests.")
    p(pdf, "- Projected returns are estimates and are not guaranteed. Actual "
            "results may differ materially from projections, including as a "
            "result of occupancy, rent growth, and exit cap rate assumptions.")
    p(pdf, "- The Sponsor's fee structure creates a potential conflict of "
            "interest between fee generation and investment performance.")
    p(pdf, "- Financing is subject to market conditions at the time of "
            "refinance or disposition.")

    pdf.output(str(OUT_DIR / "02_ppm_excerpt.pdf"))


# ---------------------------------------------------------------------------
# 3. T-12 operating statement
# ---------------------------------------------------------------------------
def gen_t12():
    pdf = new_doc()
    title(pdf, "Larkveil Residences\nTrailing-Twelve-Month (T-12) Operating Statement")
    p(pdf, "Period: Trailing 12 months ending prior to marketing launch. All figures in USD.")

    h2(pdf, "Income")
    data = [
        ["Line item", "Annual ($)"],
        ["Gross potential rent (148 units, market rent)", "2,390,000"],
        ["Vacancy loss", "(287,000)"],
        ["Concessions", "(38,000)"],
        ["Other income (laundry, parking, pet fees)", "85,000"],
        ["Effective gross income", "2,150,000"],
    ]
    pdf.set_font("Helvetica", size=10)
    with pdf.table(data):
        pass
    pdf.set_font("Helvetica", size=11)

    h2(pdf, "Operating Expenses")
    data2 = [
        ["Line item", "Annual ($)"],
        ["Payroll & administration", "295,000"],
        ["Utilities", "182,000"],
        ["Repairs & maintenance", "224,000"],
        ["Property taxes", "210,000"],
        ["Insurance", "88,000"],
        ["Management fee (3% of EGI)", "65,000"],
        ["Total operating expenses", "1,064,000"],
    ]
    pdf.set_font("Helvetica", size=10)
    with pdf.table(data2):
        pass
    pdf.set_font("Helvetica", size=11)

    h2(pdf, "Net Operating Income")
    kv(pdf, "T-12 NOI", "$1,086,000")
    kv(pdf, "Trailing average economic occupancy", "87.8%")

    pdf.output(str(OUT_DIR / "03_t12_operating_statement.pdf"))


# ---------------------------------------------------------------------------
# 4. Rent roll
# ---------------------------------------------------------------------------
def gen_rent_roll():
    pdf = new_doc()
    title(pdf, "Larkveil Residences\nRent Roll (As of Marketing Launch)")

    h2(pdf, "Unit Mix Summary")
    data = [
        ["Unit type", "Units", "Avg SF", "Occupied", "Market rent", "Avg in-place rent"],
        ["1BR / 1BA", "60", "700", "53", "$1,150", "$1,080"],
        ["2BR / 2BA", "68", "950", "60", "$1,420", "$1,340"],
        ["3BR / 2BA", "20", "1,150", "17", "$1,680", "$1,590"],
        ["Total / blended", "148", "-", "130", "-", "-"],
    ]
    pdf.set_font("Helvetica", size=9)
    with pdf.table(data):
        pass
    pdf.set_font("Helvetica", size=11)

    h2(pdf, "Occupancy Summary")
    kv(pdf, "Total units", "148")
    kv(pdf, "Occupied units", "130")
    kv(pdf, "In-place physical occupancy", "87.8% (~88%)")
    kv(pdf, "Vacant units", "18")

    p(pdf, "Note: in-place average rents reflect a mix of legacy leases and "
            "recent renewals; several units remain below current market rent, "
            "consistent with the Sponsor's renovation-driven rent-growth thesis.")

    pdf.output(str(OUT_DIR / "04_rent_roll.pdf"))


# ---------------------------------------------------------------------------
# 5. Pro forma
# ---------------------------------------------------------------------------
def gen_proforma():
    pdf = new_doc()
    title(pdf, "Larkveil Residences\n5-Year Pro Forma")

    h2(pdf, "Key Assumptions")
    kv(pdf, "Acquisition date", "Year 0")
    kv(pdf, "Year 1 stabilized occupancy assumption", "94%")
    kv(pdf, "Post-renovation rent growth (blended, Year 1)", "~7% over in-place average")
    kv(pdf, "Annual rent growth (Years 2-5)", "3.0%")
    kv(pdf, "Exit timing", "End of Year 5")
    kv(pdf, "Exit cap rate", "5.0%")

    h2(pdf, "Projected NOI by Year")
    data = [
        ["Year", "NOI ($)", "Occupancy"],
        ["Year 1", "1,351,000", "94%"],
        ["Year 2", "1,391,500", "94%"],
        ["Year 3", "1,433,200", "95%"],
        ["Year 4", "1,476,200", "95%"],
        ["Year 5", "1,520,500", "95%"],
    ]
    pdf.set_font("Helvetica", size=10)
    with pdf.table(data):
        pass
    pdf.set_font("Helvetica", size=11)

    h2(pdf, "Exit Valuation")
    kv(pdf, "Year 5 NOI", "$1,520,500")
    kv(pdf, "Applied exit cap rate", "5.0%")
    kv(pdf, "Projected gross sale price", "$30,410,000")

    p(pdf, "Year 1 NOI reflects the Sponsor's business plan to reach 94% "
            "stabilized occupancy concurrent with the renovation program. "
            "See the Offering Memorandum for the business plan narrative.")

    pdf.output(str(OUT_DIR / "05_pro_forma.pdf"))


# ---------------------------------------------------------------------------
# 6. Sponsor bio / track record
# ---------------------------------------------------------------------------
def gen_sponsor_bio():
    pdf = new_doc()
    title(pdf, "Vantrel Residential Partners\nSponsor Bio & Track Record")

    h2(pdf, "Firm Overview")
    kv(pdf, "Founded", "2011")
    kv(pdf, "Headquarters", "Marrowdale (fictional city)")
    kv(pdf, "Focus", "Value-add multifamily acquisitions")
    kv(pdf, "Total transaction volume", "$410,000,000 across 14 acquisitions")
    kv(pdf, "Realized exits", "11")
    kv(pdf, "Average realized IRR (11 exits)", "15.4%")

    h2(pdf, "Track Record Highlight")
    p(pdf, "Vantrel Residential Partners has never lost investor capital "
            "across its 11 realized exits, reflecting a disciplined "
            "underwriting and asset management approach.")

    h2(pdf, "Selected Prior Transactions")
    data = [
        ["Property", "Acquired", "Exited", "Outcome"],
        ["Quillmere Flats", "2014", "2018", "1.7x MOIC"],
        ["Brindlecrest Apartments", "2016", "2019", "Full return of capital; no profit distribution due to capex overruns"],
        ["Tamsenford Court", "2017", "2022", "2.1x MOIC"],
        ["Orrinvale Lofts", "2019", "2023", "1.6x MOIC"],
    ]
    pdf.set_font("Helvetica", size=9)
    with pdf.table(data):
        pass
    pdf.set_font("Helvetica", size=11)

    pdf.output(str(OUT_DIR / "06_sponsor_bio.pdf"))


# ---------------------------------------------------------------------------
# 7. PSA key terms
# ---------------------------------------------------------------------------
def gen_psa():
    pdf = new_doc()
    title(pdf, "Larkveil Residences\nPurchase & Sale Agreement - Key Terms")

    kv(pdf, "Seller", "Larkveil Seller SPV LLC")
    kv(pdf, "Purchase price", "$27,800,000")
    kv(pdf, "Earnest money deposit", "$500,000 total ($250,000 at execution, "
                                       "$250,000 at expiration of due diligence period)")
    kv(pdf, "Due diligence period", "45 days from execution")
    kv(pdf, "Closing", "Within 15 days of due diligence expiration (60 days from execution)")
    kv(pdf, "Financing contingency", "None - all-cash close funded via committed "
                                       "senior debt and LP equity")
    kv(pdf, "Title & survey review", "30 days from execution")

    pdf.output(str(OUT_DIR / "07_psa_key_terms.pdf"))


# ---------------------------------------------------------------------------
# 8. Market study excerpt
# ---------------------------------------------------------------------------
def gen_market_study():
    pdf = new_doc()
    title(pdf, "North Marrowdale Multifamily (Fictional Submarket)\nMarket Study Excerpt")

    h2(pdf, "Submarket Overview")
    p(pdf, "The North Marrowdale submarket has seen steady "
            "multifamily demand growth, driven by continued in-migration and "
            "proximity to the city's main highway employment corridor.")

    h2(pdf, "Cap Rate Environment")
    p(pdf, "Per broker survey data, prevailing cap rates for stabilized "
            "value-add multifamily assets in the North Marrowdale submarket "
            "currently range from 5.5% to 6.0%, with a midpoint of "
            "approximately 5.75%. Cap rates have widened modestly over the "
            "trailing 12 months in line with broader interest-rate conditions.")

    h2(pdf, "Rent Comparables")
    data = [
        ["Comp", "Unit type", "Asking rent"],
        ["Kestrelwick Place", "2BR", "$1,390"],
        ["Dunmarrow Gardens", "2BR", "$1,440"],
        ["Velloran Terrace", "2BR", "$1,460"],
    ]
    pdf.set_font("Helvetica", size=10)
    with pdf.table(data):
        pass
    pdf.set_font("Helvetica", size=11)

    h2(pdf, "Submarket Vacancy")
    kv(pdf, "Current submarket vacancy rate", "6.8%")

    pdf.output(str(OUT_DIR / "08_market_study.pdf"))


if __name__ == "__main__":
    gen_om()
    gen_ppm()
    gen_t12()
    gen_rent_roll()
    gen_proforma()
    gen_sponsor_bio()
    gen_psa()
    gen_market_study()
    print(f"Generated 8 PDFs in {OUT_DIR}")
