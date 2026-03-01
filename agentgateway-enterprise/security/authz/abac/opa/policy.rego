package abac.http

default allow = false

headers = h {
  req := object.get(input, "http_request", {})
  h := object.get(req, "headers", null)
  h != null
} else = h {
  req := object.get(object.get(object.get(input, "attributes", {}), "request", {}), "http", {})
  h := object.get(req, "headers", null)
  h != null
} else = {}

method = m {
  req := object.get(input, "http_request", {})
  m := upper(object.get(req, "method", ""))
  m != ""
} else = m {
  req := object.get(object.get(object.get(input, "attributes", {}), "request", {}), "http", {})
  m := upper(object.get(req, "method", ""))
  m != ""
} else = m {
  m := upper(object.get(headers, ":method", ""))
}

path = p {
  req := object.get(input, "http_request", {})
  p := object.get(req, "path", "")
  p != ""
} else = p {
  req := object.get(object.get(object.get(input, "attributes", {}), "request", {}), "http", {})
  p := object.get(req, "path", "")
  p != ""
} else = p {
  p := object.get(headers, ":path", "")
}

tenant = lower(object.get(headers, "x-tenant", ""))
team = lower(object.get(headers, "x-team", ""))
role = lower(object.get(headers, "x-role", ""))

required_headers_present {
  tenant != ""
  team != ""
  role != ""
}

tenant_path_valid {
  startswith(path, "/acme")
  tenant == "acme"
}

tenant_path_valid {
  startswith(path, "/contoso")
  tenant == "contoso"
}

allow {
  required_headers_present
  method != ""
  path != ""
  startswith(path, "/admin")
  team == "engineering"
  role == "employee"
}

allow {
  required_headers_present
  method != ""
  path != ""
  not startswith(path, "/admin")
  tenant_path_valid
}
