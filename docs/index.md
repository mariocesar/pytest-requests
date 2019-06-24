# Welcome to pytest-requests

`pytest-requests` will collect files test_*.yml and execute them as `requests` calls.

# Writing a requests test

Every test document requires `name` and `stages`, `variables` is optional.

```yaml
name: string
variables [Optional]: dict

stages:
  - list of requests
```

Stages are a list of the requests calls that will be apply and have a short and a long form.

```yaml
stages:
  - name [Optional]: string
    request: string
    assert: list
      - string
    register [Optional]: dict
```

The request short form will be converted to:

```yaml
request:
    url: string
    method: GET
```

The full list of options of the requests are the same for the python-requests library, for example.

```yaml
request:
    url: string
    method: post
    headers: dict
        key: string
    cookies: dict
        key: string
    data: dict
```

## Assertions

Asserts are a list of expressions that will be tested after the response is done, and are expression in python code

```yaml
assert:
  - "True is True"
  - "1 in [1, 2, 3, 4]"
```

When a response is done it adds the `response` variable to the context so you can do.

```yaml
assert:
  - "response.status_code == 200"
  - "response.json()['count'] == 3" 
```

## Extra variables

After a response and assertions are passed you can register values in the context by using the `register` option

```yaml
register:
   token: "response.json()['access_token']"
   csrf_token: "response.cookies['csrf']"
```

You can also load variables by the console, using the form `key=value`

```bash
pytest --requests-extra-vars=token=FOO
```

that will be the same as doing in the yaml file

```yaml
register:
    token: FOO
```

If you have complex nested values, you can refer to a file by prepending `@`


```bash
pytest --requests-extra-vars=@variables/foo.yml
```

Where `foo.yml` contains

```yaml
var: hello
var2: 
    var3:
    var4: 
      - Hello
      - World
```

NOTE, that the prescendence is:
    
    - Variables in `register`
    - Variables in extra-vars

## Example

Here is a complete example of Login by requesting an access token

```yaml
.authorize_headers: &authorize_headers
  headers:
    Authorization: "Bearer {access_token}"

name: Test login

stages:
  - name: Authenticate user
    request:
      url: "https://login.company.com/auth/token"
      method: POST
      data:
        username: fred
        password: 123secret
        grant_type: password
      headers:
        Authorization: Basic c2VjcmV0IHNlY3JldCBzZWNyZXQgc2VjcmV0IHNlY3JldCBzZWNyZXQgc2VjcmV0=
    assert:
      - response.status_code == 200

    register:
      access_token: response.json()['access_token']

  - name: List opportunities
    request:
      url: "https://api.company.com/opportunities"
      <<: *authorize_headers
    assert:
      - response.status_code == 200

  - name: List users
    request:
      url: "https://api.company.com/user/profile"
      <<: *authorize_headers
    assert:
      - "response.status_code == 200"
      - "'results' in response.json()"
      - "'count' in response.json()"
      - "'next' in response.json()"
      - "'previous' in response.json()"
```

## Composing tests by including files

You can use the include directive to reuse common requests like authentication requests, or common tests.

For example this is a file that have the login requests. `authenticated_user.yml`

```yaml
- name: Authenticate user
request:
  url: "https://login.company.com/auth/token"
  method: POST
  data:
    username: shall
    password: password
    grant_type: password
  headers:
    Authorization: Basic secret=
assert:
  - response.status_code == 200

register:
  access_token: response.json()['access_token']
```

Note that register directives will be loaded in the context of the test where this file is imported.

```yaml
name: Test login

stages:
  - include: authenticated_user.yml
```

The include directive mades the file path relative to the test file.
