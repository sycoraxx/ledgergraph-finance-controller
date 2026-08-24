# Demo Data Policy

This project is a simulation-only finance-controls demonstration.

## Permitted data

- Razorpay Test Mode entities created with `rzp_test_...` credentials.
- Generated orders, payments, refunds, settlement recon, bank statements, and
  ERP cashbook records.
- Deliberately planted anomalies and post-generation evaluation mutations.
- Fictional counterparties, references, approvers, and identifiers.

## Prohibited data

- Razorpay Live Mode credentials or entities.
- Real bank statements or transaction exports.
- Real accounting, ERP, invoice, customer, vendor, or payroll records.
- Personal financial data or production personally identifiable information.
- Any endpoint capable of capturing, refunding, transferring, settling, or
  otherwise moving money.

## Source labels

- `Razorpay hosted Test Mode` means the API and schema are operated by Razorpay,
  while the entities and money are simulated.
- `Simulated bank emulator` means a generated bank-style statement; it is not a
  bank export.
- `Simulated merchant ERP` means a generated cashbook fixture; it is not an
  accounting-system export.

Evaluation metrics describe these disclosed simulations only. They are not
claims about production accuracy, fraud detection, or financial assurance.
