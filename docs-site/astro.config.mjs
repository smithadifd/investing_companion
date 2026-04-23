// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://docs.smithadifd.com',
	integrations: [
		starlight({
			title: 'Investing Companion',
			description:
				'Self-hosted platform for equity tracking, analysis, and alerts.',
			social: [
				{
					icon: 'github',
					label: 'GitHub',
					href: 'https://github.com/smithadifd/investing_companion',
				},
			],
			editLink: {
				baseUrl:
					'https://github.com/smithadifd/investing_companion/edit/main/docs-site/',
			},
			sidebar: [
				{ label: 'What is Investing Companion', slug: 'index' },
				{
					label: 'Architecture',
					items: [
						{ label: 'Overview & stack', slug: 'architecture/overview' },
						{ label: 'Data flow', slug: 'architecture/data-flow' },
						{ label: 'Domain model', slug: 'architecture/domain-model' },
					],
				},
				{
					label: 'Features',
					items: [
						{ label: 'Equity dashboard & charts', slug: 'features/equity-dashboard' },
						{ label: 'Watchlists', slug: 'features/watchlists' },
						{ label: 'Market overview & ratios', slug: 'features/market-overview' },
						{ label: 'AI analysis', slug: 'features/ai-analysis' },
						{ label: 'Alerts', slug: 'features/alerts' },
						{ label: 'Trade tracker', slug: 'features/trade-tracker' },
						{ label: 'Calendar & events', slug: 'features/calendar' },
					],
				},
				{
					label: 'Running it',
					items: [
						{ label: 'Quick start (Docker)', slug: 'running/quick-start' },
						{ label: 'Configuration reference', slug: 'running/configuration' },
						{ label: 'Synology NAS deployment', slug: 'running/synology' },
						{ label: 'Backup & restore', slug: 'running/backup' },
						{ label: 'Security hardening', slug: 'running/security' },
					],
				},
				{
					label: 'Design decisions',
					items: [
						{ label: 'Why this stack?', slug: 'design-decisions/stack' },
						{ label: 'Data source strategy', slug: 'design-decisions/data-sources' },
						{ label: 'TimescaleDB for price history', slug: 'design-decisions/timescaledb' },
						{ label: 'Cache-first data flow', slug: 'design-decisions/cache-first' },
						{ label: 'FIFO trade matching', slug: 'design-decisions/fifo-matching' },
						{ label: 'AI integration approach', slug: 'design-decisions/ai-integration' },
					],
				},
				{ label: 'Roadmap & status', slug: 'roadmap' },
				{ label: 'Contributing', slug: 'contributing' },
			],
		}),
	],
});
