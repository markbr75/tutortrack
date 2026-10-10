"""Permission codenames owned by identity (E03)."""

PERMISSIONS = {
    "team.view": "View team members and invitations",
    "team.invite": "Invite people and resend or revoke invitations",
    "team.manage": "Change team members' roles, branches and status",
    "membership.transfer_ownership": "Transfer ownership of the organisation",
    "security.manage": "Change security settings (2FA enforcement, session lengths)",
    "impersonation.start": "View the portal as a tutor, client or student",
    "impersonation.write": "Make changes while impersonating (owner only by default)",
    "support.access.view": "See when TutorTrack support accessed the account",
    "support.access.manage": "Grant or revoke TutorTrack support access",
}
