/** Pick, downscale and stage attachments for the composer. */
import * as Clipboard from "expo-clipboard";
import * as DocumentPicker from "expo-document-picker";
import * as ImageManipulator from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import { File } from "expo-file-system";
import { Alert } from "react-native";

import type {
    PendingAttachment,
    PendingDocumentAttachment,
    PendingImageAttachment,
} from "../state/attachments";

export type ImageSource = "camera" | "library";

function newId(): string {
    return `att_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

export async function pickImageAttachment(
    source: ImageSource,
): Promise<PendingImageAttachment | null> {
    const permission =
        source === "camera"
            ? await ImagePicker.requestCameraPermissionsAsync()
            : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
        Alert.alert(
            "Permission needed",
            source === "camera"
                ? "Allow camera access to attach a photo."
                : "Allow photo access to attach an image.",
        );
        return null;
    }

    const result =
        source === "camera"
            ? await ImagePicker.launchCameraAsync({
                  mediaTypes: ["images"],
                  quality: 1,
              })
            : await ImagePicker.launchImageLibraryAsync({
                  mediaTypes: ["images"],
                  quality: 1,
              });
    if (result.canceled) {
        return null;
    }
    const asset = result.assets?.[0];
    if (!asset) {
        return null;
    }

    // The server accepts a 20 MB image, but base64 in a JSON body is 33%
    // larger and the phone has to hold both. 1600px / JPEG 0.7 keeps a camera
    // photo around a few hundred KB, which is plenty for the model.
    const maxWidth = 1600;
    const actions =
        asset.width && asset.width > maxWidth
            ? [{ resize: { width: maxWidth } }]
            : [];

    const output = await ImageManipulator.manipulateAsync(asset.uri, actions, {
        compress: 0.7,
        format: ImageManipulator.SaveFormat.JPEG,
        base64: true,
    });
    if (!output.base64) {
        return null;
    }

    return {
        kind: "image",
        id: newId(),
        name:
            asset.fileName ??
            `image-${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`,
        contentType: "image/jpeg",
        dataUrl: `data:image/jpeg;base64,${output.base64}`,
        previewUri: output.uri,
    };
}

const TEXT_EXTENSIONS = new Set([
    "txt",
    "md",
    "markdown",
    "json",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "csv",
    "tsv",
    "log",
    "py",
    "ts",
    "tsx",
    "js",
    "jsx",
    "css",
    "scss",
    "html",
    "xml",
    "sh",
    "bash",
    "zsh",
    "sql",
    "rs",
    "go",
    "java",
    "c",
    "h",
    "cpp",
    "hpp",
]);

const MAX_DOCUMENT_BYTES = 512 * 1024;

function extensionOf(name: string): string {
    const index = name.lastIndexOf(".");
    return index === -1 ? "" : name.slice(index + 1).toLowerCase();
}

export async function pickDocumentAttachment(): Promise<
    PendingDocumentAttachment | null
> {
    const result = await DocumentPicker.getDocumentAsync({
        type: "*/*",
        copyToCacheDirectory: true,
        multiple: false,
    });
    if (result.canceled) {
        return null;
    }
    const asset = result.assets?.[0];
    if (!asset) {
        return null;
    }
    if (!TEXT_EXTENSIONS.has(extensionOf(asset.name))) {
        Alert.alert(
            "Unsupported document",
            "Only plain-text formats are supported: .txt, .md, .json, .csv, .py, .ts, .js, .html and similar.",
        );
        return null;
    }
    if (asset.size && asset.size > MAX_DOCUMENT_BYTES) {
        Alert.alert(
            "Document too large",
            "Text attachments are limited to 512 KB.",
        );
        return null;
    }

    const text = await new File(asset.uri).text();
    if (text.includes("\u0000")) {
        Alert.alert(
            "Unsupported document",
            "That file looks binary. Only plain text can be attached.",
        );
        return null;
    }
    if (text.length > MAX_DOCUMENT_BYTES) {
        Alert.alert(
            "Document too large",
            "Text attachments are limited to 512 KB.",
        );
        return null;
    }

    return {
        kind: "document",
        id: newId(),
        name: asset.name,
        contentType: asset.mimeType ?? "text/plain",
        text,
    };
}

export async function readClipboardImage(): Promise<
    PendingImageAttachment | null
> {
    if (!(await Clipboard.hasImageAsync())) {
        Alert.alert("No image", "The clipboard does not contain an image.");
        return null;
    }
    const image = await Clipboard.getImageAsync({
        format: "jpeg",
        jpegQuality: 0.7,
    });
    if (!image) {
        return null;
    }
    if (image.data.length > 12_000_000) {
        Alert.alert("Image too large", "Copy a smaller image and try again.");
        return null;
    }
    return {
        kind: "image",
        id: newId(),
        name: "clipboard.jpg",
        contentType: "image/jpeg",
        dataUrl: image.data,
        previewUri: image.data,
    };
}
