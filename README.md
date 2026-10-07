# Mortgage Renewal Advisor

An AI-assisted mortgage renewal planning and decision-support tool.

The goal is to answer a simple question:

> **Given my mortgage situation, what are the sensible options I should consider when my current deal ends?**

Unlike a traditional mortgage calculator, the application will analyse the user's overall position and model different scenarios rather than simply returning a single calculation.

The aim is to help users understand the trade-offs involved in decisions such as:

- Overpaying the mortgage
- Reaching different loan-to-value (LTV) thresholds
- Comparing different fixed-rate periods
- Understanding changes to monthly payments
- Balancing mortgage savings against keeping cash available
- Understanding how different choices affect the overall cost of the mortgage

## Privacy first

The application is designed so that users do not need to create an account or provide personally identifiable information.

No name, email address, phone number or property address is required.

Users should be able to enter their mortgage and financial information, receive an analysis, and use the application without creating an account.

The initial version will not require persistent storage of individual mortgage cases.

## The problem

When a mortgage deal approaches its end, homeowners often need to make several decisions at the same time.

For example:

- Should I overpay before remortgaging?
- How much should I overpay?
- Is it worth reaching a lower LTV band?
- Should I keep my savings instead?
- Should I choose a 2, 3 or 5 year fixed rate?
- What will my new monthly payment be?
- How much interest could I save?
- What are the trade-offs between the different options?

Existing mortgage calculators can answer individual questions, but the goal of this project is to bring the different calculations and scenarios together.

The application should move beyond:

> **"What happens if I enter these numbers?"**

and towards:

> **"Given my situation, what are the sensible options I should consider?"**

## Core approach

The application will follow four main stages:

```text
Calculate
    |
    v
Compare
    |
    v
Explain
    |
    v
Decision support

## Disclaimer

This project is intended for educational and planning purposes only. It is not financial advice and does not replace regulated mortgage or financial advice.