## **Dummy Chat Website Bug Report**

## Overview

This report lists the issues found while reviewing the dummy website. The issues are grouped chat-wise so they are easy to review and convert into a PDF.

## **Common Issues**

### 1. Full Screen Preview Cannot Be Closed

The preview has a full screen button. After clicking it, the preview opens in full screen mode, but there is no visible button to return it to the original size.

**Expected:** The preview should have an exit full screen or restore button.

**Actual:** The preview stays in full screen mode with no clear way to return.

### 2. Steps Completed Panel Cannot Be Closed

The section that shows progress, such as "three steps completed" or similar step completion text, is already open. There is no option to close or collapse it.

**Expected:** The user should be able to close or collapse the progress panel.

**Actual:** The progress panel remains open and takes space on the screen.

### 3. Source Buttons Are Not Clickable

Source buttons are shown at the bottom, but clicking them does not redirect the user to the source.

**Expected:** Source buttons should open the direct source link.

**Actual:** The source buttons do not navigate anywhere.

### 4. Code Files Are Listed but Code Is Not Visible

In some chats, code file names are visible, but the actual code inside those files is not shown.

**Expected:** Clicking or opening a code file should show the code content.

**Actual:** Only the file names are visible.

### 5. File Downloads Use the Wrong Format

Some files download as JSON even when the visible file type is different.

**Expected:** Files should download in their correct original format, such as `.csv` or `.tsx`.

**Actual:** Files are downloaded as `.json`, which is incorrect.

### 6. Missing Download Option for Full Code

When code is generated, there is no option to download the full code package.

**Expected:** The user should be able to download the complete code as a `.zip` file.

**Actual:** Only individual files or file names are shown, and there is no full project download option.

## Chat 1 Issues

### 7. Landing Page Preview Has No Code

The first chat shows a landing page preview, but there is no related code available for that preview.

**Expected:** If a landing page preview is shown, the related code should also be available.

**Actual:** The preview is visible, but no code is provided.

### 8. CSV File Downloads as JSON

The first chat shows a CSV file. However, when the file is downloaded, it is downloaded as a JSON file.

**Expected:** The file should download as a `.csv` file.

**Actual:** The file downloads as a `.json` file.

## Chat 2 Issues

### 9. URL Upload Shows Irrelevant Preview Elements

The second chat has an article URL upload. Even though the input is a URL, the interface still shows a placeholder image and a black preview block.

**Expected:** A URL upload should show URL-related content or a clean link preview.

**Actual:** It shows unrelated placeholder-style visual elements.

### 10. URL Upload Shows Size and Dimension Fields

For the article URL upload, size and dimension fields are shown. These fields are not useful for a URL upload.

**Expected:** Size and dimension fields should only appear for files or images where they are relevant.

**Actual:** The fields appear for a URL upload.

### 11. Code Files Are Visible but Code Content Is Missing

The second chat shows code file names, but the actual code inside the files is not visible.

**Expected:** The user should be able to open and read the code files.

**Actual:** Only the code file names are shown.

### 12. Full Code Cannot Be Downloaded as ZIP

The second chat does not provide an option to download all generated code together.

**Expected:** The complete code should be downloadable as a `.zip` file.

**Actual:** There is no full code download option.

## Chat 3 Issues

### 13. Document Cannot Be Downloaded

In the third chat, the document is visible or referenced, but the user cannot download it.

**Expected:** The document should have a working download option.

**Actual:** The document cannot be downloaded.

### 14. Document Upload Shows Dimension Fields

The document upload shows dimension-related fields. These fields are not relevant for a normal document upload.

**Expected:** Document uploads should show document-related details only.

**Actual:** Dimension fields are shown unnecessarily.

## Chat 4 Issues

### 15. App Preview Has No Code

The fourth chat shows an app preview, but no related code is available.

**Expected:** If an app preview is shown, the generated code should also be available.

**Actual:** The app preview appears without code.

### 16. Document Is Not Shown in Proper Document Format

The document in the fourth chat is not displayed in a proper document format.

**Expected:** The document should be shown in a readable document viewer or proper document layout.

**Actual:** The document is not displayed correctly.

### 17. Document Cannot Be Downloaded

The document in the fourth chat also cannot be downloaded.

**Expected:** The user should be able to download the document.

**Actual:** The download option does not work or is missing.

### 18. Web Search Result Containers Are Not Clickable

The fourth chat shows web search result containers, but the containers are not clickable.

**Expected:** Clicking a web search result container should open the related source.

**Actual:** The containers do not redirect to the web search source.

### 19. Sources Do Not Redirect to Direct Links

The sources shown in the fourth chat are not clickable or do not redirect to the correct direct source.

**Expected:** Each source should open its direct source URL.

**Actual:** The source links do not work correctly.

## Chat 5 Issues

### 20. TSX File Downloads as JSON

In the fifth chat, a `.tsx` file is available. When downloaded, it downloads as a JSON file instead of a TSX file.

**Expected:** The file should download with the `.tsx` extension and correct content.

**Actual:** The file downloads as `.json`.

### 21. Admin Analytics Preview Has No Visible Code

The Admin Analytics Preview shows the preview and code file names, but the actual code is not visible.

**Expected:** The user should be able to view the code for the Admin Analytics Preview.

**Actual:** Only the preview and file names are visible.  