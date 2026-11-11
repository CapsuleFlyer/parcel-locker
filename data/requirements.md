# Smart Parcel Locker: Behavioural Requirements

States: `AVAILABLE`, `RESERVED`, `OCCUPIED`, `MAINTENANCE`.

Operations:
- `RESERVE`: reserve an available locker using a customer ID.
- `CANCEL`: cancel a reservation.
- `DEPOSIT`: deposit against the active reservation and reservation code.
- `RETRIEVE`: retrieve using the parcel retrieval code.
- `EXPIRE`: expire a reservation whose expiry has been reached.
- `DISABLE`: place an available locker into maintenance.
- `ENABLE`: return a maintenance locker to service.
- `INVALID_ACCESS`: attempt an operation with an invalid credential.

Rules:
1. Reserve is accepted only in `AVAILABLE`; successful reservation enters `RESERVED`.
2. A reservation creates code `R-<customer_id>`.
3. Cancel is accepted only in `RESERVED`; it returns to `AVAILABLE`.
4. Deposit is accepted only in `RESERVED` with the correct reservation code; it enters `OCCUPIED`.
5. Successful deposit creates retrieval code `P-<customer_id>`.
6. Retrieve is accepted only in `OCCUPIED` with the correct retrieval code; it returns to `AVAILABLE`.
7. Successful retrieval clears all customer and credential data.
8. Expire is accepted only in `RESERVED` when the explicit `expired` flag is true; it returns to `AVAILABLE`.
9. Disable is accepted only in `AVAILABLE`; it enters `MAINTENANCE`.
10. Enable is accepted only in `MAINTENANCE`; it returns to `AVAILABLE`.
11. Invalid credentials are rejected without changing state or stored credentials.
12. Any rejected operation must not mutate system state.

Assumptions:
- One locker is tested at a time.
- Time is controlled by the explicit `expired` Boolean; do not use wall-clock time.
- All operations return `Result(accepted, message)`.
- You may add requirements and edge cases, but document them.
