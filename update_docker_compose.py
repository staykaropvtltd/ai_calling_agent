import yaml

with open("docker-compose.yml", "r") as f:
    compose = yaml.safe_load(f)

# Modify the api service to run the root main.py directly
compose["services"]["api"]["build"]["context"] = "."
compose["services"]["api"]["build"]["dockerfile"] = "services/api/Dockerfile"
if "profiles" in compose["services"]["api"]:
    del compose["services"]["api"]["profiles"]

with open("docker-compose.yml", "w") as f:
    yaml.dump(compose, f, default_flow_style=False, sort_keys=False)
