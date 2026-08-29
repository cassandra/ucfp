<img src="docs/assets/logo.png" alt="Landfall" width="128">

# Landfall

**When can you retire? Find out.**

Landfall is a free, private tool that forecasts your financial future, and lets
you explore how today's choices change it. Built on a robust double-entry model,
it's yours to use with no ads, no upsell, and no need to hand over your data.

## What it does

- **Forecast**: project your finances year by year into the future. Every number
  is fully drillable, down to the account and the individual transaction, so you
  can always see *why* the forecast says what it says.
- **Explore**: change a plan or an assumption and immediately see how the forecast
  shifts. Ask "what if I retire two years earlier?" or "what if I spend $500 more a
  month?" and watch the outcome move.

## Two ways to use it

- **Free hosted version: [landfall.cassandrahq.com](https://landfall.cassandrahq.com).**
  Nothing to install and no password to remember. Add your email only when you want
  to reach your data from another device and be sure you never lose access to it.
- **Self-host your own private instance.** One command, and your data never leaves
  your machine:

  ```shell
  curl -fsSL https://raw.githubusercontent.com/cassandra/ucfp/master/install.sh | bash
  ```

  Then open [http://localhost:9666](http://localhost:9666). See the
  **[Self-Hosting Guide](docs/SelfHosting.md)** for network access, updates, and
  advanced configuration.

## Free and private

Landfall has no commercial motive, which is exactly why it doesn't behave like the
alternatives. There are no ads, no upsell, no crippled free tier, and no marketing
email. It uses no third-party tracking, stores no passwords or credentials (only the
balance summaries you type), and encrypts your figures in transit and at rest. If you
want total control, self-host and your data stays entirely on your own computer.

> Landfall is a planning tool, not financial advice: its forecasts are estimates
> based on the numbers and assumptions you provide. Verify anything that matters, and
> for real decisions, check with a qualified professional.

## Documentation

- **[Self-Hosting Guide](docs/SelfHosting.md)**: install, manage, update, and configure your own instance
- **[FAQ](docs/FAQ.md)**: hosted vs. self-hosted, privacy, trust, and common questions
- **[Security](SECURITY.md)**: security postures and how to report a vulnerability
- **[Contributing](CONTRIBUTING.md)**: feedback, bug reports, and getting involved
- **[Changelog](CHANGELOG.md)**: release history

## License

Landfall is **free and source-available for noncommercial use** under the
**PolyForm Noncommercial License 1.0.0**: personal, educational, research, and
hobby use at no cost. Commercial use requires a separate license. See
**[LICENSE.md](LICENSE.md)** for full terms.

Copyright © 2026 POMDP, LLC.
