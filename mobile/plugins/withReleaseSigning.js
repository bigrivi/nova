/**
 * Adds a release signing config when credentials are available.
 *
 * Credentials come from environment variables (CI) or `mobile/signing.properties`
 * (local, gitignored). Without either, the generated project keeps Expo's debug
 * signing so `expo prebuild` still works for development.
 */
const fs = require("node:fs");
const path = require("node:path");

const { withAppBuildGradle } = require("@expo/config-plugins");

const ENV_KEYS = {
    storeFile: "NOVA_KEYSTORE_FILE",
    storePassword: "NOVA_KEYSTORE_PASSWORD",
    keyAlias: "NOVA_KEY_ALIAS",
    keyPassword: "NOVA_KEY_PASSWORD",
};

function readProperties() {
    const file = path.join(__dirname, "..", "signing.properties");
    if (!fs.existsSync(file)) {
        return null;
    }
    const props = {};
    for (const line of fs.readFileSync(file, "utf8").split("\n")) {
        const match = line.match(/^\s*([^#=]+?)\s*=\s*(.*)$/);
        if (match) {
            props[match[1]] = match[2].trim();
        }
    }
    return props;
}

function readSigning() {
    const fromEnv = {};
    for (const [key, name] of Object.entries(ENV_KEYS)) {
        if (process.env[name]) {
            fromEnv[key] = process.env[name];
        }
    }
    const signing = Object.keys(fromEnv).length === 4 ? fromEnv : readProperties();
    if (!signing?.storeFile || !signing.storePassword || !signing.keyAlias) {
        return null;
    }
    signing.keyPassword = signing.keyPassword || signing.storePassword;
    signing.storeFile = path.isAbsolute(signing.storeFile)
        ? signing.storeFile
        : path.resolve(__dirname, "..", signing.storeFile);
    return signing;
}

function escape(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

module.exports = function withReleaseSigning(config) {
    return withAppBuildGradle(config, (cfg) => {
        const signing = readSigning();
        if (!signing) {
            return cfg;
        }
        let contents = cfg.modResults.contents;
        if (contents.includes("novaRelease")) {
            return cfg;
        }
        contents = contents.replace(
            /signingConfigs \{\n/,
            [
                "signingConfigs {",
                "        novaRelease {",
                `            storeFile file("${escape(signing.storeFile)}")`,
                `            storePassword "${escape(signing.storePassword)}"`,
                `            keyAlias "${escape(signing.keyAlias)}"`,
                `            keyPassword "${escape(signing.keyPassword)}"`,
                "        }",
                "",
            ].join("\n"),
        );
        contents = contents.replace(
            /(release \{\n(?:[ \t]*\/\/[^\n]*\n)*[ \t]*)signingConfig signingConfigs\.debug/,
            "$1signingConfig signingConfigs.novaRelease",
        );
        cfg.modResults.contents = contents;
        return cfg;
    });
};
