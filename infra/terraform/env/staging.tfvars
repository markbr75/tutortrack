environment                = "staging"
region                     = "eu-west-2"
app_domain                 = "staging.tutortrack.app"
acm_certificate_arn        = "arn:aws:acm:eu-west-2:000000000000:certificate/replace-me"
cloudfront_certificate_arn = "arn:aws:acm:us-east-1:000000000000:certificate/replace-me"
backend_image              = "000000000000.dkr.ecr.eu-west-2.amazonaws.com/tutortrack-backend:bootstrap"
web_desired_count          = 1
