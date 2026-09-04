"""India-specific financial constants used to compute correct ground truth."""

GST_ON_MDR_RATE = 0.18          # 18% GST on the gateway's MDR fee
TDS_RATE_194O = 0.001           # 0.1% TDS under Sec 194O (post Apr-2026 transition)
TDS_RATE_LEGACY = 0.01          # old 1% rate -- used to simulate a "wrong rate" bug

MDR_RATE_CARD = 0.0175          # 1.75% typical card MDR
MDR_RATE_UPI_BANK = 0.0         # zero-interchange bank-account UPI
MDR_RATE_UPI_WALLET = 0.009     # wallet-on-UPI, interchange-bearing (~0.9%)
MDR_RATE_UPI_RUPAY_CREDIT = 0.02  # RuPay-credit-on-UPI, interchange above INR 2000
MDR_RATE_NETBANKING = 0.02

VENDOR_COMMISSION_RATE_RANGE = (0.08, 0.20)  # 8-20% marketplace commission
