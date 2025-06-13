import React from 'react';
import { makeStyles, Spinner, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
    container: {
        height: '100vh',
        width: '100vw',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: tokens.colorNeutralBackground1,
    },
    label: {
        marginTop: '1rem',
        color: tokens.colorBrandForeground1,
        fontSize: tokens.fontSizeBase500,
    }
});

interface LoadingSpinnerProps {
    label?: string;
}

export default function LoadingSpinner({ label = "Loading..." }: LoadingSpinnerProps) {
    const classes = useStyles();
    
    return (
        <div className={classes.container}>
            <Spinner 
                size="extra-large"
                appearance="primary"
                label={label}
                labelPosition="after"
            />
        </div>
    );
} 