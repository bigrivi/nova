/**
 * Wrap markdown tables in a horizontal scroll view.
 *
 * streamdown-rn renders every table cell with `flex: 1`, so a wide table
 * squeezes its columns until every word wraps. The renderer has no override
 * hook, so the compiled table function is patched in place after install.
 * The patch is idempotent and fails loudly when the upstream text changes.
 */
import { readFileSync, writeFileSync } from "node:fs";

const file = "node_modules/streamdown-rn/dist/renderers/ASTRenderer.js";
const originalImport =
    "import { Text, View, ScrollView, Image, Platform } from 'react-native';";
const patchedImport =
    "import { Text, View, ScrollView, Image, Platform, Dimensions } from 'react-native';";
const originalOpen = `    const headerRow = rows[0];
    const bodyRows = rows.slice(1);
    return (<View key={key} style={{ marginBottom: theme.spacing.block }}>`;
const patchedOpen = `    const headerRow = rows[0];
    const bodyRows = rows.slice(1);
    const columnCount = Math.max(headerRow.children.length, ...bodyRows.map((row) => row.children.length), 1);
    const viewport = Dimensions.get('window').width - 32;
    const contentWidth = Math.max(viewport, columnCount * 132);
    return (<ScrollView key={key} horizontal nestedScrollEnabled style={{ marginBottom: theme.spacing.block }}>
      <View style={{ minWidth: contentWidth }}>`;
const originalClose = `        </View>))}
    </View>);
}
/**
 * Auto-sized image component`;
const patchedClose = `        </View>))}
      </View>
    </ScrollView>);
}
/**
 * Auto-sized image component`;

let source;
try {
    source = readFileSync(file, "utf8");
} catch (error) {
    console.error(`[patch-streamdown] cannot read ${file}: ${error.message}`);
    process.exit(1);
}

if (source.includes("columnCount * 132")) {
    console.log("[patch-streamdown] already applied");
    process.exit(0);
}
if (!source.includes(originalOpen) || !source.includes(originalClose)) {
    console.error(
        "[patch-streamdown] upstream table renderer changed; update the patch",
    );
    process.exit(1);
}

writeFileSync(
    file,
    source
        .replace(originalImport, patchedImport)
        .replace(originalOpen, patchedOpen)
        .replace(originalClose, patchedClose),
);
console.log("[patch-streamdown] table horizontal scroll applied");
