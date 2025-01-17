# Themes

A theme is a collection of files that are included in the frontend during a certain time period.
For example, the easter theme is active during the month of April, and it makes the entire stregsystem delightfully yellow.

## Themes directory structure

Refer back to this overview if you are unsure where to put your theme files.

```
stregsystem/
    themes.json -- The main configuration file
    static/
        stregsystem/
            themes/
                mytheme/ -- (the name of your theme)
                    mytheme.css
                    mytheme.js
                    image.svg 
                    ...
    templates/
        stregsystem/
            themes/
                mytheme/ -- (the name of your theme)
                    mytheme.html

```

## Add a theme

To add a new theme, you must add a new entry in the `themes.json` file. Here is a template:
```json
{
    "name": "mytheme",
    "html": "mytheme.html",
    "css": "mytheme.css",
    "js": "mytheme.js",
    "begin": {
        "month": 1,
        "day": 1
    },
    "end": {
        "month": 12,
        "day": 31
    }
}
```
Only `name`, `begin.month` and `end.month` are required. You can safely remove the other fields.

The dates are inclusive, which means that the theme will be shown on the `begin` and `end` dates that you define. If you don't define a day, the theme will be shown for the entire month.

When you have added the theme entry, you need to add the corresponding files that it points to. Go back and read the [directory structure](#themes-directory-structure) to see where each type of file needs to go.

- If you define the `html` key, the html file will be added to the bottom of the stregystem frontend inside a `div` with the id `theme-content`.
- If you define the `css` key, the css file will be loaded as part of the stregsystem frontend.
- If you define the `js` key, the js file will be loaded as a module in the stregsystem frontend.

If you have extra files, such as an image file, you can put them in the static theme directory.

## Link to other theme files

If you need the path to some of your extra files, you can use the following helper methods.

### In html

You can use the `themes_static` template tag to get the path to the static themes folder. Use it like this:

```html
<img src="{{ '/stregsystem/themes/fireworks/rocket.svg' | relative_url }}" alt="Rocket">
```

There is also `themes_template` for the template themes folder.

### In js

You can use the global variable `themes_static_url` to get the path to the static themes folder. Use it like this:

```js
const src = themes_static_url + "mytheme/image.svg";
```

### In css

There is no solution for static css files, but you can use inline styles in the html template:

```html
<img src="{{ '/static/stregsystem/themes/fireworks/rocket.svg' | relative_url }}" alt="Rocket">
```

## Style the frontend

TODO: should contain a list of classes and id's that you can target to safely style the frontend, but those id's need to be added to the frontend first.

## Test a theme

When you have added the json entry and corresponding files, you can load the themes configuration and run the test server.

First, load the new theme configuration into the test fixture:

```sh
python manage.py reloadthemes fixture
```

Now start the test server with the themes test fixture:

```sh
python manage.py testserver stregsystem/fixtures/testdata-themes.json
```

If you're doing rapid prorotyping, you can temporarily edit the `begin` and `end` dates such that your theme will be shown on your current date.

Alternatively, you can access the [admin panel](./README.md#using-testdata) and find the `Themes` view. Each theme has an `override` that you can set to `Force show`, which will make the theme visible no matter what the date settings are. Note that the theming system updates once every 30 seconds, so there can be a small delay before the theme is shown.

## Loading themes in production

If you are running the server in production mode, you can load the themes configuration into your database:

```sh
python manage.py reloadthemes database
```
