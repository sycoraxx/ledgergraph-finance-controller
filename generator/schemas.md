# Data Schemas

The checked-in CSV files under `generator/schemas/` are conversions of the
official Razorpay XLSX sample reports. They are the column-name source of truth;
this summary exists only for quick reference.

### orders.csv
`id,amount,amount_paid,amount_due,currency,receipt,offer_id,status,attempts,notes,created_at`

### payments.csv
`id,amount,currency,status,order_id,invoice_id,international,method,amount_refunded,amount_transferred,refund_status,captured,description,card_id,card,bank,wallet,vpa,email,contact,notes,fee,tax,error_code,error_description,created_at,card_type,card_network`

### refunds.csv
`id,amount,currency,payment_id,notes,receipt,created_at,contact,email,arn`

### settlements-recon
`transaction_entity,entity_id,amount,currency,fee (exclusive tax),tax,debit,credit,payment_method,card_type,issuer_name,entity_created_at,payment_captured_at,payment_notes,refund_notes,arn,entity_description,order_id,order_receipt,order_notes,dispute_id,dispute_created_at,dispute_reason,settlement_id,settled_at,settlement_utr,settled_by`

The files above preserve the official sample-report column names. The following
two schemas are explicitly synthetic independent sources used by the bank-risk
benchmark; they are not claimed to be Razorpay export schemas.

### bank_statement.csv
`bank_txn_id,txn_date,value_date,txn_timestamp_utc,transaction_type,narration,ref_no,debit,credit,balance`

### cashbook.csv
`event_id,event_timestamp_utc,value_date,direction,amount,counterparty,reference,purpose,approved_by`
