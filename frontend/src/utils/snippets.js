function escapeForSingleQuotedShell(value) {
  return String(value).replace(/'/g, "'\"'\"'");
}

function routeFor(apiName, endpointPath) {
  const path = endpointPath || '';
  if (!path) {
    return `/${apiName}`;
  }
  if (path.startsWith('/')) {
    return `/${apiName}${path}`;
  }
  return `/${apiName}/${path}`;
}

function toPythonLiteral(value, indent = 0) {
  const spacing = ' '.repeat(indent);

  if (Array.isArray(value)) {
    if (!value.length) {
      return '[]';
    }
    const items = value.map((item) => `${' '.repeat(indent + 4)}${toPythonLiteral(item, indent + 4)}`);
    return `\n${spacing}[\n${items.join(',\n')}\n${spacing}]`;
  }

  if (value && typeof value === 'object') {
    const entries = Object.entries(value);
    if (!entries.length) {
      return '{}';
    }
    const lines = entries.map(
      ([key, inner]) => `${' '.repeat(indent + 4)}${JSON.stringify(key)}: ${toPythonLiteral(inner, indent + 4).trimStart()}`
    );
    return `\n${spacing}{\n${lines.join(',\n')}\n${spacing}}`;
  }

  if (typeof value === 'string') {
    return JSON.stringify(value);
  }
  if (typeof value === 'boolean') {
    return value ? 'True' : 'False';
  }
  if (value === null) {
    return 'None';
  }
  return String(value);
}

function normalizeMultipartFields(example) {
  const fields = { ...(example?.fields || {}) };
  const fileField = example?.file_field;

  if (fileField && !(fileField in fields) && example?.file_name) {
    fields[fileField] = `@${example.file_name}`;
  }

  return fields;
}

function pythonDataObject(fields, fileField) {
  const entries = Object.entries(fields).filter(([key]) => key !== fileField);
  if (!entries.length) {
    return '{}';
  }

  const body = entries
    .map(([key, value]) => `${JSON.stringify(key)}: ${JSON.stringify(String(value))}`)
    .join(', ');
  return `{${body}}`;
}

function fileNameFromValue(value, fallback) {
  if (typeof value === 'string' && value.startsWith('@')) {
    return value.slice(1);
  }
  return fallback || 'upload.bin';
}

function buildMultipartFormLines(fields, fileField, fileName, fileComment) {
  const lines = [];

  Object.entries(fields).forEach(([key, value]) => {
    if (key === fileField) {
      return;
    }
    lines.push(`form.append(${JSON.stringify(key)}, ${JSON.stringify(String(value))});`);
  });

  if (fileComment) {
    lines.push(`// ${fileComment}`);
  }
  lines.push(`const uploadFile = new File([], ${JSON.stringify(fileName)});`);
  lines.push(`form.append(${JSON.stringify(fileField)}, uploadFile, ${JSON.stringify(fileName)});`);

  return lines;
}

function generateJsonSnippets(route, example) {
  const body = example?.body || { model: 'gpt-4o-mini' };
  const compact = JSON.stringify(body);
  const compactSafe = escapeForSingleQuotedShell(compact);
  const prettyJson = JSON.stringify(body, null, 2);
  const pythonPayload = toPythonLiteral(body).trimStart();

  return {
    curl: `API="https://alittlebitofmoney.com"

STEP1=$(curl -s -X POST "$API${route}" \\
  -H "Content-Type: application/json" \\
  -d '${compactSafe}')

INVOICE=$(echo "$STEP1" | jq -r '.invoice')
echo "Pay this invoice with your wallet:"
echo "$INVOICE"

read -r -p "Preimage: " PREIMAGE
curl -s "$API/redeem?preimage=$PREIMAGE" | jq .`,

    python: `import requests

API = "https://alittlebitofmoney.com"

# Step 1: Send request -> get 402 + invoice
step1 = requests.post(f"{API}${route}", json=${pythonPayload})
invoice = step1.json()["invoice"]
print("Pay this invoice with your wallet:")
print(invoice)

# Step 2: Pay with your wallet, paste preimage
preimage = input("Preimage: ").strip()

# Step 3: Redeem
result = requests.get(f"{API}/redeem", params={"preimage": preimage})
print(result.json())`,

    javascript: `const API = "https://alittlebitofmoney.com";

// Step 1: Send request -> get 402 + invoice
const step1 = await fetch(\`${'${API}'}${route}\`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(${prettyJson}),
});

const { invoice } = await step1.json();
console.log("Pay this invoice with your wallet:", invoice);

// Step 2: Pay with your wallet, get preimage
const preimage = prompt("Preimage:");

// Step 3: Redeem
const result = await fetch(\`${'${API}'}/redeem?preimage=${'${preimage}'}\`);
console.log(await result.json());`,
  };
}

function generateMultipartSnippets(route, example) {
  const fields = normalizeMultipartFields(example);
  const fileField = example?.file_field || 'file';
  const rawFileValue = fields[fileField] || `@${example?.file_name || 'upload.bin'}`;
  const fileName = fileNameFromValue(rawFileValue, example?.file_name);
  const fileComment = example?.file_comment || `${fileField} file from your app`;

  const curlFields = Object.entries(fields)
    .map(([key, value]) => {
      const asString = String(value);
      const formValue = asString.startsWith('@') ? asString : asString.replace(/"/g, '\\"');
      return `-F "${key}=${formValue}"`;
    })
    .join(' \\\n  ');

  const dataObject = pythonDataObject(fields, fileField);
  const jsLines = buildMultipartFormLines(fields, fileField, fileName, fileComment);

  return {
    curl: `API="https://alittlebitofmoney.com"

STEP1=$(curl -s -X POST "$API${route}" \\
  ${curlFields})

INVOICE=$(echo "$STEP1" | jq -r '.invoice')
echo "Pay this invoice with your wallet:"
echo "$INVOICE"

read -r -p "Preimage: " PREIMAGE
curl -s "$API/redeem?preimage=$PREIMAGE" | jq .`,

    python: `import requests

API = "https://alittlebitofmoney.com"

# Step 1: Send request -> get 402 + invoice
with open("${fileName}", "rb") as upload_file:
    step1 = requests.post(
        f"{API}${route}",
        data=${dataObject},
        files={"${fileField}": upload_file},
    )

invoice = step1.json()["invoice"]
print("Pay this invoice with your wallet:")
print(invoice)

# Step 2: Pay with your wallet, paste preimage
preimage = input("Preimage: ").strip()

# Step 3: Redeem
result = requests.get(f"{API}/redeem", params={"preimage": preimage})
print(result.json())`,

    javascript: `const API = "https://alittlebitofmoney.com";

// Step 1: Send request -> get 402 + invoice
const form = new FormData();
${jsLines.join('\n')}

const step1 = await fetch(\`${'${API}'}${route}\`, {
  method: "POST",
  body: form,
});

const { invoice } = await step1.json();
console.log("Pay this invoice with your wallet:", invoice);

// Step 2: Pay with your wallet, get preimage
const preimage = prompt("Preimage:");

// Step 3: Redeem
const result = await fetch(\`${'${API}'}/redeem?preimage=${'${preimage}'}\`);
console.log(await result.json());`,
  };
}

export function generateSnippets(apiName, endpointPath, example) {
  const route = routeFor(apiName, endpointPath);
  if (!example || !example.content_type) {
    return generateJsonSnippets(route, { content_type: 'json', body: { model: 'gpt-4o-mini' } });
  }

  if (example.content_type === 'multipart') {
    return generateMultipartSnippets(route, example);
  }
  return generateJsonSnippets(route, example);
}
