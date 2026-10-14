# Personal data breach notification

**Owner:** DPO · **Review:** every 6 months

A personal data breach is a security incident that leads to the accidental or unlawful
destruction, loss, alteration, unauthorised disclosure of, or access to, personal data.

## Clock
- **T0**: the moment we are reasonably certain a breach happened. Record it in the incident doc.
- **T0 + 48 hours**: tell affected customers (controllers), as the DPA promises, even if facts
  are still incomplete; follow up as we learn more.
- **T0 + 72 hours**: where TutorTrack is the **controller** (our own account data), notify the
  regulator unless the breach is unlikely to result in a risk to people: the ICO (UK), the
  lead EU supervisory authority, the OAIC (Australia, "eligible data breach" within 30 days of
  suspicion) or US state regulators as their laws require. For customer data the customer is
  the controller and notifies their regulator; we give them what they need to do it in time.
- **Without undue delay**: tell affected people directly when the risk is high (we do this for
  customers on request, or for our own account data).

## Telling customers
1. The DPO and IC agree the affected organisations and the facts.
2. Send the notice to each organisation's owners and admins from the platform admin
   **Notify customers** tool (E30) or, until it ships, by email from the incident mailbox using
   the template below; record who was told and when in the incident doc.
3. Post on the status page if many customers are affected.

### Template
> Subject: Security incident affecting your TutorTrack account
>
> On {{date}} we became aware of {{what happened}}. It affected {{data categories}} of
> {{number}} people in your organisation between {{start}} and {{end}}. We have
> {{containment}}. You may need to notify your data protection regulator within 72 hours of
> this notice and tell the people affected if the risk to them is high. Our DPO,
> {{name, email}}, will help you with the details: {{record ids}}.

## Records
Every breach, notified or not, goes in the breach register: facts, effects, actions, and the
reason for any decision not to notify.
