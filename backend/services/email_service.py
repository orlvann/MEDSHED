# backend/services/email_service.py
"""
Email Service.

Handles sending emails via SMTP for:
- Password setup/reset for new users
- Account notifications
- System alerts

Uses Python's built-in smtplib for SMTP communication.
For production, consider using aiosmtplib for async operations.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from backend.config import settings

logger = logging.getLogger(__name__)


def send_password_setup_email(
    *,
    email: str,
    token: str,
    first_name: str,
    last_name: str,
) -> None:
    """
    Send a password setup email to a new user.
    
    Args:
        email: Recipient email address
        token: Password reset token (will be included in the link)
        first_name: User's first name (for personalization)
        last_name: User's last name (for personalization)
        
    Raises:
        Exception: If email sending fails
        
    Notes:
        - Email contains a link to set up password: {FRONTEND_URL}/set-password?token={token}
        - Token expires in 48 hours
        - HTML email for better presentation
    """
    try:
        # Build the password setup link
        setup_link = f"{settings.FRONTEND_URL}/set-password?token={token}"
        
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Set Up Your MedShed Password"
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = email
        
        # Plain text version
        text_body = f"""
Hello {first_name} {last_name},

Welcome to MedShed! An administrator has created an account for you.

To complete your account setup and create your password, please click the link below:

{setup_link}

This link will expire in 48 hours.

If you did not request this account, please ignore this email or contact your administrator.

Best regards,
The MedShed Team
        """.strip()
        
        # HTML version (better presentation)
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background-color: #3b82f6;
            color: white;
            padding: 20px;
            text-align: center;
            border-radius: 5px 5px 0 0;
        }}
        .content {{
            background-color: #f9fafb;
            padding: 30px;
            border: 1px solid #e5e7eb;
        }}
        .button {{
            display: inline-block;
            background-color: #3b82f6;
            color: white !important;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .footer {{
            color: #6b7280;
            font-size: 0.875rem;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #e5e7eb;
        }}
        .warning {{
            color: #dc2626;
            font-size: 0.875rem;
            margin-top: 15px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Welcome to MedShed!</h1>
        </div>
        <div class="content">
            <p>Hello <strong>{first_name} {last_name}</strong>,</p>
            
            <p>An administrator has created an account for you in the MedShed system.</p>
            
            <p>To complete your account setup and create your password, please click the button below:</p>
            
            <div style="text-align: center;">
                <a href="{setup_link}" class="button" style="color: white !important;">Set Up My Password</a>
            </div>
            
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #3b82f6;">{setup_link}</p>
            
            <p class="warning"><strong>Important:</strong> This link will expire in 48 hours.</p>
            
            <div class="footer">
                <p>If you did not request this account, please ignore this email or contact your administrator.</p>
                <p>Best regards,<br>The MedShed Team</p>
            </div>
        </div>
    </div>
</body>
</html>
        """.strip()
        
        # Attach both versions
        part1 = MIMEText(text_body, "plain")
        part2 = MIMEText(html_body, "html")
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            # Use TLS if not using a local test server
            if settings.SMTP_HOST not in ["localhost", "127.0.0.1", "mailhog", "maildev"]:
                server.starttls()
            
            # Authenticate if credentials provided
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            
            # Send
            server.sendmail(settings.SMTP_FROM_EMAIL, email, msg.as_string())
        
        logger.info(f"Password setup email sent to {email}")
        
    except Exception as e:
        logger.error(f"Failed to send password setup email to {email}: {str(e)}")
        # Don't raise - we don't want email failures to block user creation
        # In production, you might want to queue this for retry


def send_admin_created_email(
    *,
    email: str,
    token: str,
) -> None:
    """
    Send a password setup email to a newly created admin user.
    
    Args:
        email: Recipient email address
        token: Password reset token (will be included in the link)
        
    Raises:
        Exception: If email sending fails
        
    Notes:
        - Similar to doctor password setup but tailored for admin users
        - Email contains a link to set up password: {FRONTEND_URL}/set-password?token={token}
        - Token expires in 48 hours
    """
    try:
        # Build the password setup link
        setup_link = f"{settings.FRONTEND_URL}/set-password?token={token}"
        
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Set Up Your MedShed Admin Password"
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = email
        
        # Plain text version
        text_body = f"""
Hello,

An administrator account has been created for you in the MedShed system.

To complete your account setup and create your password, please click the link below:

{setup_link}

This link will expire in 48 hours.

If you did not request this account, please ignore this email or contact your system administrator.

Best regards,
The MedShed Team
        """.strip()
        
        # HTML version
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background-color: #7c3aed;
            color: white;
            padding: 20px;
            text-align: center;
            border-radius: 5px 5px 0 0;
        }}
        .content {{
            background-color: #f9fafb;
            padding: 30px;
            border: 1px solid #e5e7eb;
        }}
        .button {{
            display: inline-block;
            background-color: #7c3aed;
            color: white !important;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .footer {{
            color: #6b7280;
            font-size: 0.875rem;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #e5e7eb;
        }}
        .warning {{
            color: #dc2626;
            font-size: 0.875rem;
            margin-top: 15px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Admin Account Created</h1>
        </div>
        <div class="content">
            <p>Hello,</p>
            
            <p>An administrator account has been created for you in the MedShed system.</p>
            
            <p>To complete your account setup and create your password, please click the button below:</p>
            
            <div style="text-align: center;">
                <a href="{setup_link}" class="button" style="color: white !important;">Set Up My Password</a>
            </div>
            
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #7c3aed;">{setup_link}</p>
            
            <p class="warning"><strong>Important:</strong> This link will expire in 48 hours.</p>
            
            <div class="footer">
                <p>If you did not request this account, please ignore this email or contact your system administrator.</p>
                <p>Best regards,<br>The MedShed Team</p>
            </div>
        </div>
    </div>
</body>
</html>
        """.strip()
        
        # Attach both versions
        part1 = MIMEText(text_body, "plain")
        part2 = MIMEText(html_body, "html")
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            # Use TLS if not using a local test server
            server.starttls()
            
            # Authenticate if credentials provided
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            
            # Send
            server.sendmail(settings.SMTP_FROM_EMAIL, email, msg.as_string())
        
        logger.info(f"Admin password setup email sent to {email}")
        
    except Exception as e:
        logger.error(f"Failed to send admin password setup email to {email}: {str(e)}")
        # Don't raise - we don't want email failures to block user creation


def send_password_reset_email(
    *,
    to_email: str,
    token: str,
) -> None:
    """
    Send a password reset email to a user who requested it.
    
    Args:
        to_email: Recipient email address
        token: Password reset token (will be included in the link)
        
    Raises:
        Exception: If email sending fails
        
    Notes:
        - Email contains a link to reset password: {FRONTEND_URL}/set-password?token={token}
        - Token expires in 48 hours
        - Uses the same token system as password setup
    """
    try:
        # Build the password reset link
        reset_link = f"{settings.FRONTEND_URL}/set-password?token={token}"
        
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Reset Your MedShed Password"
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = to_email
        
        # Plain text version
        text_body = f"""
Hello,

We received a request to reset your MedShed password.

To reset your password, please click the link below:

{reset_link}

This link will expire in 48 hours.

If you did not request a password reset, please ignore this email. Your password will remain unchanged.

Best regards,
The MedShed Team
        """.strip()
        
        # HTML version (better presentation)
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background-color: #3b82f6;
            color: white;
            padding: 20px;
            text-align: center;
            border-radius: 5px 5px 0 0;
        }}
        .content {{
            background-color: #f9fafb;
            padding: 30px;
            border: 1px solid #e5e7eb;
        }}
        .button {{
            display: inline-block;
            background-color: #3b82f6;
            color: white !important;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .footer {{
            color: #6b7280;
            font-size: 0.875rem;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #e5e7eb;
        }}
        .warning {{
            color: #dc2626;
            font-size: 0.875rem;
            margin-top: 15px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Password Reset Request</h1>
        </div>
        <div class="content">
            <p>Hello,</p>
            
            <p>We received a request to reset your MedShed password.</p>
            
            <p>To reset your password, please click the button below:</p>
            
            <div style="text-align: center;">
                <a href="{reset_link}" class="button" style="color: white !important;">Reset My Password</a>
            </div>
            
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #3b82f6;">{reset_link}</p>
            
            <p class="warning"><strong>Important:</strong> This link will expire in 48 hours.</p>
            
            <div class="footer">
                <p>If you did not request a password reset, please ignore this email. Your password will remain unchanged.</p>
                <p>Best regards,<br>The MedShed Team</p>
            </div>
        </div>
    </div>
</body>
</html>
        """.strip()
        
        # Attach both versions
        part1 = MIMEText(text_body, "plain")
        part2 = MIMEText(html_body, "html")
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            # Use TLS if not using a local test server
            if settings.SMTP_HOST not in ["localhost", "127.0.0.1", "mailhog", "maildev"]:
                server.starttls()
            
            # Authenticate if credentials provided
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            
            # Send
            server.sendmail(settings.SMTP_FROM_EMAIL, to_email, msg.as_string())
        
        logger.info(f"Password reset email sent to {to_email}")
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {to_email}: {str(e)}")
        raise  # Raise for password reset since it's user-initiated


def send_deadline_changed_email(
    *,
    email: str,
    first_name: str,
    last_name: str,
    year: int,
    month: int,
    new_deadline: str,
) -> None:
    """
    Send notification email when preferences deadline is changed.

    Args:
        email: Recipient email address
        first_name: Doctor's first name
        last_name: Doctor's last name
        year: Year of the period
        month: Month of the period (1-12)
        new_deadline: New deadline datetime string (ISO format)

    Notes:
        - Sent to all active doctors when admin changes deadline
        - Email failures are logged but don't raise (non-blocking)
    """
    try:
        from datetime import datetime

        # Parse and format deadline for display
        deadline_dt = datetime.fromisoformat(new_deadline.replace("Z", "+00:00"))
        deadline_formatted = deadline_dt.strftime("%B %d, %Y at %H:%M")

        # Month name
        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        month_name = month_names[month - 1]

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"MedShed: Preferences Deadline Updated for {month_name} {year}"
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = email

        # Plain text version
        text_body = f"""
Hello {first_name} {last_name},

The deadline for submitting your scheduling preferences for {month_name} {year} has been updated.

New Deadline: {deadline_formatted}

Please ensure you submit your preferences before this deadline. You can access the preferences form by logging into MedShed.

If you have already submitted your preferences, no further action is required.

Best regards,
The MedShed Team
        """.strip()

        # HTML version
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background-color: #3b82f6;
            color: white;
            padding: 20px;
            text-align: center;
            border-radius: 5px 5px 0 0;
        }}
        .content {{
            background-color: #f9fafb;
            padding: 30px;
            border: 1px solid #e5e7eb;
        }}
        .deadline-box {{
            background-color: #fef3c7;
            border: 1px solid #f59e0b;
            border-radius: 5px;
            padding: 15px;
            margin: 20px 0;
            text-align: center;
        }}
        .deadline-label {{
            color: #92400e;
            font-size: 0.875rem;
            margin-bottom: 5px;
        }}
        .deadline-value {{
            color: #78350f;
            font-size: 1.25rem;
            font-weight: bold;
        }}
        .footer {{
            color: #6b7280;
            font-size: 0.875rem;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #e5e7eb;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Preferences Deadline Updated</h1>
        </div>
        <div class="content">
            <p>Hello <strong>{first_name} {last_name}</strong>,</p>

            <p>The deadline for submitting your scheduling preferences for <strong>{month_name} {year}</strong> has been updated.</p>

            <div class="deadline-box">
                <div class="deadline-label">New Deadline</div>
                <div class="deadline-value">{deadline_formatted}</div>
            </div>

            <p>Please ensure you submit your preferences before this deadline. You can access the preferences form by logging into MedShed.</p>

            <p>If you have already submitted your preferences, no further action is required.</p>

            <div class="footer">
                <p>Best regards,<br>The MedShed Team</p>
            </div>
        </div>
    </div>
</body>
</html>
        """.strip()

        # Attach both versions
        part1 = MIMEText(text_body, "plain")
        part2 = MIMEText(html_body, "html")
        msg.attach(part1)
        msg.attach(part2)

        # Send email
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            # Use TLS if not using a local test server
            if settings.SMTP_HOST not in ["localhost", "127.0.0.1", "mailhog", "maildev"]:
                server.starttls()

            # Authenticate if credentials provided
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

            # Send
            server.sendmail(settings.SMTP_FROM_EMAIL, email, msg.as_string())

        logger.info(f"Deadline change notification sent to {email}")

    except Exception as e:
        logger.error(f"Failed to send deadline notification to {email}: {str(e)}")
        # Don't raise - email failures shouldn't block deadline updates

