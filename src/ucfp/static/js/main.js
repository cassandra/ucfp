(function() {

    // window.__APP_CONFIG__ is injected by the server template (see the
    // client-config context processor). This module is the ONLY client code
    // that reads that raw global; it relays the values via App.config so every
    // other JS module reads App.config.* instead of touching the global.
    const injected = window.__APP_CONFIG__ ?? {};

    const App = {

        config: {
            DEBUG: injected.DEBUG ?? false,
            ENVIRONMENT: injected.ENVIRONMENT ?? 'unknown',
            VERSION: injected.VERSION ?? null,
        },

        // ----- General DOM / form helpers (public wrappers over the private
        // implementations below) -----
        generateUniqueId: function() {
            return _generateUniqueId();
        },
        setCookie: function( name, value, days = 365, sameSite = 'Lax' ) {
            return _setCookie( name, value, days, sameSite );
        },
        getCookie: function( name ) {
            return _getCookie( name );
        },
        submitForm: function( formElement ) {
            return _submitForm( formElement );
        },
        updateFormDirtyState: function( formElement ) {
            return _updateFormDirtyState( formElement );
        },
        togglePasswordField: function( toggleCheckbox ) {
            return _togglePasswordField( toggleCheckbox );
        },
        toggleDetails: function( elementId ) {
            return _toggleDetails( elementId );
        },

        // ----- Geometry helpers -----
        getScreenCenterPoint: function( element ) {
            return _getScreenCenterPoint( element );
        },
        getRotationAngle: function( centerX, centerY, startX, startY, endX, endY ) {
            return _getRotationAngle( centerX, centerY, startX, startY, endX, endY );
        },
        normalizeAngle: function( angle ) {
            return _normalizeAngle( angle );
        },

        // ----- Debug helpers (no-op unless App.config.DEBUG) -----
        displayEventInfo: function( label, event ) {
            return _displayEventInfo( label, event );
        },
        displayElementInfo: function( label, element ) {
            return _displayElementInfo( label, element );
        },
    };

    window.App = App;

    function _generateUniqueId() {
        return 'id-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    }

    function _setCookie( name, value, days, sameSite ) {
        const expires = new Date();
        expires.setTime( expires.getTime() + days * 24 * 60 * 60 * 1000 );
        const secureFlag = sameSite === 'None' ? '; Secure' : '';
        document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires.toUTCString()}; path=/; SameSite=${sameSite}${secureFlag}`;
        return true;
    }

    function _getCookie( name ) {
        const nameEQ = `${encodeURIComponent(name)}=`;
        const cookies = document.cookie.split(';');
        for ( let i = 0; i < cookies.length; i++ ) {
            let cookie = cookies[i].trim();
            if (cookie.startsWith( nameEQ )) {
                return decodeURIComponent( cookie.substring( nameEQ.length ));
            }
        }
        return null;
    }

    function _submitForm( formElement ) {
        let form = $(formElement).closest('form');
        if ( App.config.DEBUG ) { console.debug( 'Submitting form:', formElement, form ); }
        $(form).submit();
    }

    function _updateFormDirtyState( formElement ) {
        // Compares each field's current value to its server-rendered
        // initial (``defaultValue`` / ``defaultChecked`` /
        // ``defaultSelected``), toggles ``.dirty`` on the field's
        // label, and enables/disables the form's submit button(s).
        // ``defaultValue`` etc. survive value mutations but are reset
        // by any re-render of the form HTML, so a successful save's
        // returned markup naturally re-baselines without explicit
        // state-reset code.
        let anyDirty = false;
        const fields = formElement.querySelectorAll( 'input, select, textarea' );
        fields.forEach( function( field ) {
            // Skip hidden CSRF tokens, submit buttons, and unnamed
            // controls that aren't part of the form's data payload.
            if ( ! field.name ) { return; }
            if ( field.type === 'hidden' ) { return; }
            if ( field.type === 'submit' || field.type === 'button' ) { return; }
            let fieldDirty = false;
            if ( field.type === 'checkbox' || field.type === 'radio' ) {
                fieldDirty = ( field.checked !== field.defaultChecked );
            } else if ( field.tagName === 'SELECT' ) {
                for ( const option of field.options ) {
                    if ( option.selected !== option.defaultSelected ) {
                        fieldDirty = true;
                        break;
                    }
                }
            } else {
                fieldDirty = ( field.value !== field.defaultValue );
            }
            if ( field.id ) {
                const label = formElement.querySelector(
                    'label[for="' + field.id + '"]'
                );
                if ( label ) {
                    label.classList.toggle( 'dirty', fieldDirty );
                }
            }
            if ( fieldDirty ) { anyDirty = true; }
        });
        const submitButtons = formElement.querySelectorAll( 'button[type="submit"]' );
        submitButtons.forEach( function( button ) {
            button.disabled = ! anyDirty;
        });
    }

    function _togglePasswordField( toggleCheckbox ) {
        let passwordField = $(toggleCheckbox).closest('.input-group')
            .find('input[type="password"], input[type="text"]');
        if ( toggleCheckbox.checked ) {
            passwordField.attr('type', 'text');
            $('label[for="' + $(toggleCheckbox).attr('id') + '"]').text('Hide');
        } else {
            passwordField.attr('type', 'password');
            $('label[for="' + $(toggleCheckbox).attr('id') + '"]').text('Show');
        }
    }

    function _toggleDetails( elementId ) {
        if (!elementId || elementId.trim() === '') {
            console.warn('_toggleDetails called with empty elementId');
            return;
        }
        const el = document.getElementById(elementId);
        if (el) {
            $(el).toggle();
        } else {
            console.warn('_toggleDetails: Element not found with ID:', elementId);
        }
    }

    function _getScreenCenterPoint( element ) {
        try {
            let rect = $(element)[0].getBoundingClientRect();
            if ( rect ) {
                return {
                    x: rect.left + ( rect.width / 2.0 ),
                    y: rect.top + ( rect.height / 2.0 )
                };
            }
        } catch (e) {
            console.debug( `Problem getting bounding box: ${e}` );
        }
        return null;
    }

    function _getRotationAngle( centerX, centerY, startX, startY, endX, endY ) {

        const startVectorX = startX - centerX;
        const startVectorY = startY - centerY;

        const endVectorX = endX - centerX;
        const endVectorY = endY - centerY;

        const startAngle = Math.atan2( startVectorY, startVectorX );
        const endAngle = Math.atan2( endVectorY, endVectorX );

        let angleDifference = endAngle - startAngle;

        // Normalize the angle to be between -π and π
        if ( angleDifference > Math.PI ) {
            angleDifference -= 2 * Math.PI;
        } else if ( angleDifference < -Math.PI ) {
            angleDifference += 2 * Math.PI;
        }

        return angleDifference * ( 180 / Math.PI );
    }

    function _normalizeAngle(angle) {
        return (angle % 360 + 360) % 360;
    }

    function _displayEventInfo ( label, event ) {
        if ( ! App.config.DEBUG ) { return; }
        if ( ! event ) {
            console.log( 'No element to display info for.' );
            return;
        }
        console.log( `${label} Event:
    Type: ${event.type},
    Key: ${event.key},
    KeyCode: ${event.keyCode},
    Pos: ( ${event.clientX}, ${event.clientY} )` );
    }

    function _displayElementInfo( label, element ) {
        if ( ! App.config.DEBUG ) { return; }
        if ( ! element ) {
            console.log( 'No element to display info for.' );
            return;
        }
        const elementTag = $(element).prop('tagName');
        const elementId = $(element).attr('id') || 'No ID';
        const elementClasses = $(element).attr('class') || 'No Classes';

        let rectStr = 'No Bounding Rect';
        try {
            let rect = $(element)[0].getBoundingClientRect();
            if ( rect ) {
                rectStr = `Dim: ${rect.width}px x ${rect.height}px,
    Pos: left=${rect.left}px, top=${rect.top}px`;
            }
        } catch (e) {
        }

        let offsetStr = 'No Offset';
        const offset = $(element).offset();
        if ( offset ) {
            offsetStr = `Offset: ( ${offset.left}px,  ${offset.top}px )`;
        }

        let svgStr = 'Not an SVG';
        if ( elementTag == 'svg' ) {
            let viewBox = $(element).attr( 'viewBox' );
            if ( viewBox != null ) {
                svgStr = `Viewbox: ${viewBox}`;
            } else {
                svgStr = 'No viewbox attribute';
            }
        }

        console.log( `${label}:
    Name: ${elementTag},
    Id: ${elementId},
    Classes: ${elementClasses},
    ${svgStr},
    ${offsetStr},
    ${rectStr}`) ;
    }

})();
