<img src="assets/logo.png" alt="App Logo" width="128">

# Development Guide

For those who want to work on Landfall itself. This page covers what you need and
where to start; the detailed guides live under [`dev/`](dev/). If you just want to
use Landfall, see the [Self-Hosting Guide](SelfHosting.md) instead.

## Requirements and Dependencies

- Python 3.11 (or higher) - installed.
- Redis - installed and running locally (bundled automatically in Docker deployments).
- A GitHub account.

## Tech Stack

- Django 5.2 (back-end)
- Javascript using jQuery 3.7 (front-end)
- Bootstrap 4 (CSS)
- SQLite (database)
- Redis (caching)

## Getting Started

Follow these steps in order to begin contributing:

- **[Environment Setup](dev/Setup.md)** - Install and configure your development environment
- **[Contributor Workflow](dev/ContributorWorkflow.md)** - Git workflow and pull request process
