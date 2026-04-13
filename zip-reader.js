(function attachZipReader(global) {
  "use strict";

  const EOCD_SIGNATURE = 0x06054b50;
  const CENTRAL_DIRECTORY_SIGNATURE = 0x02014b50;
  const LOCAL_FILE_HEADER_SIGNATURE = 0x04034b50;
  const MAX_COMMENT_LENGTH = 0xffff;

  function readUint16(view, offset) {
    return view.getUint16(offset, true);
  }

  function readUint32(view, offset) {
    return view.getUint32(offset, true);
  }

  function decodeBytes(bytes) {
    return new TextDecoder("utf-8").decode(bytes);
  }

  function findEndOfCentralDirectory(view) {
    const minOffset = Math.max(0, view.byteLength - (22 + MAX_COMMENT_LENGTH));

    for (let offset = view.byteLength - 22; offset >= minOffset; offset -= 1) {
      if (readUint32(view, offset) === EOCD_SIGNATURE) {
        return offset;
      }
    }

    throw new Error("ZIP 구조를 찾지 못했습니다. 인스타그램 export ZIP인지 확인해 주세요.");
  }

  function sliceBytes(bytes, start, end) {
    return bytes.subarray(start, end);
  }

  async function inflateRaw(compressedBytes) {
    if (typeof DecompressionStream === "undefined") {
      throw new Error("이 브라우저는 ZIP 해제를 지원하지 않습니다. 최신 Chrome, Edge, Safari에서 열어 주세요.");
    }

    let decompressedStream;

    try {
      decompressedStream = new Blob([compressedBytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    } catch (error) {
      throw new Error("이 브라우저의 ZIP 해제 기능이 부족합니다. 최신 Chrome, Edge, Safari에서 다시 열어 주세요.");
    }

    return new Uint8Array(await new Response(decompressedStream).arrayBuffer());
  }

  function parseCentralDirectory(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const eocdOffset = findEndOfCentralDirectory(view);
    const totalEntries = readUint16(view, eocdOffset + 10);
    const centralDirectoryOffset = readUint32(view, eocdOffset + 16);
    const entries = [];
    let cursor = centralDirectoryOffset;

    for (let index = 0; index < totalEntries; index += 1) {
      if (readUint32(view, cursor) !== CENTRAL_DIRECTORY_SIGNATURE) {
        throw new Error("ZIP 중앙 디렉터리를 읽는 중 문제가 생겼습니다.");
      }

      const compressionMethod = readUint16(view, cursor + 10);
      const compressedSize = readUint32(view, cursor + 20);
      const uncompressedSize = readUint32(view, cursor + 24);
      const filenameLength = readUint16(view, cursor + 28);
      const extraLength = readUint16(view, cursor + 30);
      const commentLength = readUint16(view, cursor + 32);
      const localHeaderOffset = readUint32(view, cursor + 42);
      const filenameStart = cursor + 46;
      const filenameEnd = filenameStart + filenameLength;
      const filename = decodeBytes(sliceBytes(bytes, filenameStart, filenameEnd));

      entries.push({
        compressedSize,
        compressionMethod,
        filename,
        localHeaderOffset,
        uncompressedSize,
      });

      cursor = filenameEnd + extraLength + commentLength;
    }

    return entries;
  }

  async function readEntryBytes(bytes, entry) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const headerOffset = entry.localHeaderOffset;

    if (readUint32(view, headerOffset) !== LOCAL_FILE_HEADER_SIGNATURE) {
      throw new Error(entry.filename + " 파일 헤더를 읽는 중 문제가 생겼습니다.");
    }

    const localFilenameLength = readUint16(view, headerOffset + 26);
    const localExtraLength = readUint16(view, headerOffset + 28);
    const dataStart = headerOffset + 30 + localFilenameLength + localExtraLength;
    const dataEnd = dataStart + entry.compressedSize;
    const compressedBytes = sliceBytes(bytes, dataStart, dataEnd);

    if (entry.compressionMethod === 0) {
      return compressedBytes;
    }

    if (entry.compressionMethod === 8) {
      const inflated = await inflateRaw(compressedBytes);

      if (entry.uncompressedSize !== 0 && inflated.byteLength !== entry.uncompressedSize) {
        throw new Error(entry.filename + " 압축 해제 결과가 예상한 크기와 다릅니다.");
      }

      return inflated;
    }

    throw new Error(entry.filename + " 파일은 지원하지 않는 압축 방식입니다.");
  }

  async function parseZipArchive(file) {
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const centralDirectoryEntries = parseCentralDirectory(bytes);
    const entryMap = new Map();

    centralDirectoryEntries.forEach((entry) => {
      entryMap.set(entry.filename, {
        filename: entry.filename,
        async text() {
          const entryBytes = await readEntryBytes(bytes, entry);
          return decodeBytes(entryBytes);
        },
      });
    });

    return entryMap;
  }

  global.InstagramZipReader = {
    parseZipArchive,
  };
})(window);
