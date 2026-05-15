from datetime import date

from django.test import TestCase

from .views import summarize_company_nav_entries

# Create your tests here.


class CompanyNavSummaryTests(TestCase):

	def test_groups_regular_schemes_by_company(self):
		entries = [
			{
				'company_name': 'Axis Mutual Fund',
				'scheme_code': '117446',
				'isin_div_payout_growth': 'INF846K01CB0',
				'isin_div_reinvestment': '-',
				'scheme_name': 'Axis Banking & PSU Debt Fund - Regular Plan - Growth option',
				'nav': '2743.7826',
				'nav_date': date(2026, 5, 8),
				'raw_line': 'regular row 1',
			},
			{
				'company_name': 'Axis Mutual Fund',
				'scheme_code': '120439',
				'isin_div_payout_growth': 'INF846K01CT2',
				'isin_div_reinvestment': '-',
				'scheme_name': 'Axis Banking & PSU Debt Fund - Regular Plan - Monthly IDCW',
				'nav': '1033.9706',
				'nav_date': date(2026, 5, 8),
				'raw_line': 'regular row 2',
			},
			{
				'company_name': 'Axis Mutual Fund',
				'scheme_code': '120438',
				'isin_div_payout_growth': 'INF846K01CR6',
				'isin_div_reinvestment': '-',
				'scheme_name': 'Axis Banking & PSU Debt Fund - Direct Plan - Growth Option',
				'nav': '2836.1289',
				'nav_date': date(2026, 5, 8),
				'raw_line': 'direct row',
			},
		]

		summary = summarize_company_nav_entries(entries)

		self.assertEqual(len(summary), 1)
		self.assertEqual(summary[0]['company_name'], 'Axis Mutual Fund')
		self.assertEqual([item['scheme_code'] for item in summary[0]['nav']], ['117446', '120439'])
		self.assertEqual(summary[0]['nav'][0]['scheme_name'], 'Axis Banking & PSU Debt Fund - Regular Plan - Growth option')
		self.assertEqual(summary[0]['nav'][0]['net_asset_value'], '2743.7826')
