# Provider outage

| Provider | Effect | What to do |
|---|---|---|
| Stripe | Card payments, auto-pay and our own billing pause | Post a notice ("Card payments are delayed"). Collections retry by themselves (Temporal); webhooks are redelivered by Stripe. |
| Twilio | SMS fail | Messages are marked failed with the error; email still sends. Resend important reminders after recovery from the message log. |
| Postmark / SES | Email delayed | Messages stay queued and retry. Check bounces after recovery. |
| Temporal Cloud | Workflows (dunning, invoice runs, reminders) pause | Starts and signals fail and the outbox retries them; nothing is lost. Raise a ticket with Temporal; check workflow backlog after recovery. |

Always post a platform notice so customers see the banner, and update the status page.
